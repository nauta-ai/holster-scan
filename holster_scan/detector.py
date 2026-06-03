#!/usr/bin/env python3
"""Offline probe for hallucinated/slopsquatted package imports.

This is intentionally small and self-contained. It does not query npm, PyPI, or
any package index; the point is to test whether static name signals plus the
project's declared dependencies produce a useful first-pass detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import re
from typing import Iterable

from .resolver import (
    normalize_distribution,
    resolve_import,
    exists_on_registry,
    import_root,
    is_maintained,
)


POPULAR_PACKAGES = {
    # PyPI: scientific/data/ML
    "numpy", "pandas", "scipy", "scikit-learn", "sklearn", "matplotlib",
    "seaborn", "plotly", "bokeh", "statsmodels", "sympy", "numba", "polars",
    "pyarrow", "xarray", "pillow", "opencv-python", "imageio",
    "tensorflow", "keras", "torch", "torchvision", "torchaudio",
    "transformers", "datasets", "tokenizers", "accelerate", "diffusers",
    "sentence-transformers", "xgboost", "lightgbm", "catboost",
    # PyPI: web/API/dev
    "requests", "urllib3", "httpx", "aiohttp", "fastapi", "flask", "django",
    "starlette", "uvicorn", "gunicorn", "celery", "redis", "sqlalchemy",
    "psycopg2", "psycopg2-binary", "pymongo", "alembic", "pytest",
    "coverage", "tox", "black", "ruff", "mypy", "isort", "pydantic",
    "click", "typer", "rich", "jinja2", "beautifulsoup4", "bs4", "lxml",
    "scrapy", "selenium", "playwright", "paramiko", "cryptography",
    "pyyaml", "python-dotenv", "python-dateutil", "pytz", "tqdm", "loguru",
    "openai", "anthropic", "langchain", "langchain-core",
    "langchain-community", "llama-index", "chromadb", "faiss-cpu",
    "pinecone", "pinecone-client", "weaviate-client", "qdrant-client",
    # npm: frameworks/runtime
    "react", "react-dom", "next", "vue", "nuxt", "svelte", "astro",
    "angular", "express", "fastify", "koa", "hapi", "nestjs",
    "typescript", "ts-node", "tsx", "vite", "webpack", "rollup", "parcel",
    "babel", "eslint", "prettier", "jest", "vitest", "mocha", "chai",
    "cypress", "playwright", "storybook", "tailwindcss", "postcss",
    "autoprefixer", "sass", "less", "styled-components", "emotion",
    "framer-motion", "gsap", "three", "d3", "chart.js", "echarts",
    "lodash", "underscore", "axios", "node-fetch", "got", "superagent",
    "moment", "dayjs", "date-fns", "zod", "joi", "yup", "ajv",
    "uuid", "nanoid", "commander", "yargs", "chalk", "ora", "inquirer",
    "dotenv", "debug", "winston", "pino", "nodemon", "pm2",
    "mongoose", "prisma", "sequelize", "knex", "pg", "mysql2", "sqlite3",
    "redis", "ioredis", "socket.io", "ws", "graphql", "apollo-server",
    "@apollo/client", "@reduxjs/toolkit", "redux", "zustand", "mobx",
    "react-router", "react-router-dom", "formik", "react-hook-form",
    "date-fns", "lucide-react", "class-variance-authority", "clsx",
    "tailwind-merge", "@tanstack/react-query", "swr", "openai",
    "@langchain/core", "@langchain/openai", "llamaindex", "@vercel/ai",
    "ai", "@next/env", "@sentry/node", "@sentry/react", "stripe",
    "firebase", "supabase", "@supabase/supabase-js", "sharp",
}


HALLUCINATED_FAMILIES = {
    # known naming families where LLMs often invent utility/client packages
    "openai-api": "openai",
    "openai-client": "openai",
    "openai-tools": "openai",
    "langchain-tools": "langchain",
    "langchain-utils": "langchain",
    "llama-index-tools": "llama-index",
    "langchain-openai-utils": "langchain",
    "torch-utils": "torch",
    "huggingface-transformer": "transformers",
    "transformer-utils": "transformers",
    "numpy-utils": "numpy",
    "pandas-utils": "pandas",
    "requests-utils": "requests",
    "tensorflow-utils": "tensorflow",
}


# Module roots that are never third-party packages.
SPECIAL_IGNORE = {"__main__", "__init__", "__future__", "__future_"}

# Suffixes LLMs hallucinate onto a real package root to invent a helper/utility
# package ("<popular>-utils"). Deliberately EXCLUDES -client/-api/-sdk because
# many of those are real (chromadb-client, qdrant-client, pinecone-client...).
HALLUCINATION_SUFFIXES = {
    "utils", "util", "tools", "helper", "helpers",
    "wrapper", "wrappers", "ext", "toolkit", "extras",
}

# Python 2 / legacy module names that are commonly imported behind a
# try/except ImportError shim; never slopsquats.
LEGACY_COMPAT = {
    "cpickle", "cstringio", "stringio", "urllib2", "urlparse",
    "httplib", "queue", "thread", "copy-reg", "configparser2",
}


@dataclass(frozen=True)
class Finding:
    package: str
    reason: str
    confidence: str


def normalize(name: str) -> str:
    name = name.strip()
    if name.startswith("@"):
        # Keep npm scopes meaningful, but normalize separators.
        name = name.replace("/", "-")
    return re.sub(r"[-_.]+", "-", name).strip("-").lower()


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def is_transposition(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diffs = [i for i, (ca, cb) in enumerate(zip(a, b)) if ca != cb]
    return len(diffs) == 2 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]


def plural_variant(a: str, b: str) -> bool:
    return a.rstrip("s") == b.rstrip("s") and a != b


def namespace_abuse(candidate: str, popular: str) -> bool:
    scoped = candidate.startswith("@") and popular in candidate
    if "-" not in candidate and not scoped:
        return False
    parts = [p.lstrip("@") for p in candidate.split("-") if p]
    if popular in parts and candidate != popular:
        return True
    return any(candidate.startswith(f"{popular}-") or candidate.endswith(f"-{popular}") for _ in [0])


def nearest_popular(name: str) -> tuple[str | None, int, float]:
    best_name = None
    best_dist = 999
    best_ratio = 0.0
    for popular in POPULAR_PACKAGES:
        cand = normalize(name)
        pop = normalize(popular)
        dist = edit_distance(cand, pop)
        ratio = SequenceMatcher(None, cand, pop).ratio()
        if (dist, -ratio) < (best_dist, -best_ratio):
            best_name, best_dist, best_ratio = popular, dist, ratio
    return best_name, best_dist, best_ratio


def strong_confusable(norm: str, popular_norm: set[str]) -> tuple[str | None, str | None]:
    """A HIGH-confidence look-alike of a popular package that should be flagged
    even when the name happens to exist on PyPI (published typosquats are the
    dangerous case). Returns (popular_target, reason) or (None, None)."""
    if norm in popular_norm:
        return None, None
    # "<popular>-utils" style hallucinated helper packages.
    if "-" in norm:
        head, _, tail = norm.rpartition("-")
        if tail in HALLUCINATION_SUFFIXES and head in popular_norm:
            return head, f"hallucinated '-{tail}' helper of popular package {head}"
    # Typo / near-duplicate of a popular root.
    for pop in popular_norm:
        # Require a non-trivial length so 3-char roots (git/got, ai) don't collide.
        if min(len(norm), len(pop)) < 4:
            continue
        if edit_distance(norm, pop) <= 1 or is_transposition(norm, pop) or plural_variant(norm, pop):
            return pop, f"typo/near-duplicate of popular package {pop}"
    return None, None


def detect(
    imported_packages: Iterable[str],
    declared_deps: Iterable[str],
    optional_imports: Iterable[str] = (),
    registry_exists=None,
    maintenance_check=None,
) -> list[Finding]:
    registry_exists = registry_exists or exists_on_registry
    maintenance_check = maintenance_check or is_maintained
    declared_norm = {normalize_distribution(dep) for dep in declared_deps}
    popular_norm = {normalize(pkg) for pkg in POPULAR_PACKAGES}
    hallucinated_norm = {normalize(k): (k, v) for k, v in HALLUCINATED_FAMILIES.items()}
    optional_roots = {import_root(p) for p in optional_imports}
    findings: list[Finding] = []

    for package in imported_packages:
        norm = normalize(package)
        root = import_root(package)
        if not norm or root in SPECIAL_IGNORE or root.startswith("__"):
            continue

        resolved = resolve_import(package)
        resolved_norm = {normalize_distribution(dist) for dist in resolved.distributions}
        if resolved.is_stdlib or (resolved_norm & declared_norm):
            continue

        if norm in popular_norm or norm in LEGACY_COMPAT:
            continue

        if norm in hallucinated_norm:
            _, target = hallucinated_norm[norm]
            findings.append(Finding(package, f"hallucinated package family near {target}", "high"))
            continue

        # Strong look-alikes are evaluated BEFORE the plain registry oracle, so a
        # typosquat that has actually been published to PyPI (panda, beautifulsoup,
        # django-utils) is still caught instead of being waved through by "it
        # exists." The escape hatch: if the look-alike is itself an actively
        # maintained real package (psycopg, uuid-utils, tokenizer), it is NOT a
        # squat - fall through and let the oracle suppress it.
        tgt, why = strong_confusable(norm, popular_norm)
        if tgt:
            candidates = set(resolved.distributions) | {package}
            real_and_maintained = any(
                registry_exists(d) is True and maintenance_check(d) for d in candidates
            )
            if not real_and_maintained:
                findings.append(Finding(package, why, "high"))
                continue

        # Guarded/optional imports (inside try/except ImportError, capability gates)
        # are real optional deps, not hallucinations - suppress unless they were a
        # strong look-alike above.
        if root in optional_roots:
            continue

        # Registry oracle: a real-but-undeclared package (cohere, dask, langchain-
        # anthropic) EXISTS on PyPI -> legit, suppress. A true slopsquat (reqeusts)
        # 404s. Suppress only on a confirmed hit (True); unknown/None still flags so
        # it stays useful offline.
        candidates = set(resolved.distributions) | {package}
        if any(registry_exists(d) is True for d in candidates):
            continue

        namespace_target = next((popular for popular in popular_norm if namespace_abuse(norm, popular)), None)
        if namespace_target:
            findings.append(Finding(package, f"undeclared namespace/package family near popular package {namespace_target}", "high"))
            continue

        nearest, distance, ratio = nearest_popular(package)
        nearest_norm = normalize(nearest or "")
        if nearest and (
            distance <= 2
            or (distance <= 3 and min(len(norm), len(nearest_norm)) <= 6 and ratio >= 0.60)
            or is_transposition(norm, nearest_norm)
            or plural_variant(norm, nearest_norm)
            or namespace_abuse(norm, nearest_norm)
            or (distance <= 4 and ratio >= 0.84)
        ):
            findings.append(Finding(package, f"undeclared and close to popular package {nearest}", "high"))
            continue

    return findings


POSITIVE_CORPUS = [
    # Fake-but-plausible LLM/slopsquat-style names assembled from public research
    # themes: typos, invented utility packages, invented clients, and namespace abuse.
    "requestes", "reqeusts", "request", "numpy-utils", "numppy",
    "pandas-utils", "panda", "scikitlearn", "scikit-learn-utils",
    "matplotlip", "tenserflow", "tensorflow-utils", "pytoch",
    "torch-utils", "openai-client", "openai-api", "openai-tools",
    "openai_utils", "langchain-utils", "langchain-tools",
    "langchain-openai-utils", "llama-index-tools", "llamaindex-utils",
    "chromadb-client", "pinecone-utils", "beautifulsoup", "pilow",
    "flask-login2", "django-utils", "fastapi-utils", "express-utils",
    "react-dom-utils", "@openai/sdk", "@langchain/tools", "@numpy/core",
    "huggingface-transformer", "transformer-utils", "dotenv-safe-loader",
]


NEGATIVE_IMPORTS = [
    "requests", "httpx", "urllib3", "numpy", "pandas", "scipy",
    "sklearn", "matplotlib", "seaborn", "plotly", "polars", "pyarrow",
    "pillow", "cv2", "tensorflow", "keras", "torch", "transformers",
    "datasets", "openai", "anthropic", "langchain", "langchain-community",
    "llama-index", "chromadb", "qdrant-client", "fastapi", "flask",
    "django", "sqlalchemy", "pydantic", "pytest", "ruff", "black",
    "beautifulsoup4", "bs4", "lxml", "pyyaml", "dotenv", "dateutil",
    "react", "react-dom", "next", "vue", "svelte", "express",
    "fastify", "typescript", "vite", "webpack", "eslint", "prettier",
    "jest", "vitest", "tailwindcss", "lodash", "axios", "zod",
    "uuid", "prisma", "@tanstack/react-query", "lucide-react",
]


def evaluate() -> dict:
    declared = set(NEGATIVE_IMPORTS)
    pos_findings = detect(POSITIVE_CORPUS, declared)
    neg_findings = detect(NEGATIVE_IMPORTS, declared)

    pos_hit = {f.package for f in pos_findings}
    neg_hit = {f.package for f in neg_findings}

    return {
        "positive_count": len(POSITIVE_CORPUS),
        "negative_count": len(NEGATIVE_IMPORTS),
        "true_positives": len(pos_hit),
        "false_negatives": len(POSITIVE_CORPUS) - len(pos_hit),
        "false_positives": len(neg_hit),
        "recall": len(pos_hit) / len(POSITIVE_CORPUS),
        "false_positive_rate": len(neg_hit) / len(NEGATIVE_IMPORTS),
        "positive_findings": [f.__dict__ for f in pos_findings],
        "negative_findings": [f.__dict__ for f in neg_findings],
        "misses": [p for p in POSITIVE_CORPUS if p not in pos_hit],
        "false_alarms": [n for n in NEGATIVE_IMPORTS if n in neg_hit],
    }


def main() -> None:
    print(json.dumps(evaluate(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
