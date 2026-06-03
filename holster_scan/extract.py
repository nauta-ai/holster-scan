from __future__ import annotations

import ast
import configparser
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Iterable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


SKIP_DIRS = {
    ".git",
    ".hg",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".eggs",
    ".next",
    "coverage",
}

JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}


@dataclass(frozen=True)
class ImportRecord:
    package: str
    path: Path
    line: int
    ecosystem: str
    guarded: bool = False


@dataclass
class EcosystemInputs:
    ecosystem: str
    imports: set[str] = field(default_factory=set)
    declared_deps: set[str] = field(default_factory=set)
    optional_imports: set[str] = field(default_factory=set)
    records: list[ImportRecord] = field(default_factory=list)


@dataclass
class ProjectInputs:
    root: Path
    python: EcosystemInputs
    javascript: EcosystemInputs

    @property
    def ecosystems(self) -> tuple[EcosystemInputs, EcosystemInputs]:
        return self.python, self.javascript


def extract_project(root: Path) -> ProjectInputs:
    root = root.resolve()
    py_imports, py_guarded, py_records = imported_python(root)
    js_imports, js_records = imported_javascript(root)
    return ProjectInputs(
        root=root,
        python=EcosystemInputs(
            ecosystem="python",
            imports=py_imports,
            declared_deps=declared_python_deps(root),
            optional_imports=py_guarded,
            records=py_records,
        ),
        javascript=EcosystemInputs(
            ecosystem="javascript",
            imports=js_imports,
            declared_deps=declared_javascript_deps(root),
            optional_imports=set(),
            records=js_records,
        ),
    )


def dep_name(spec: str) -> str | None:
    spec = spec.strip()
    if not spec or spec.startswith(("#", "-r ", "--", "git+", "http://", "https://")):
        return None
    spec = spec.split(";", 1)[0].strip()
    spec = re.sub(r"\[[^\]]+\]", "", spec)
    match = re.match(r"([A-Za-z0-9_.-]+)", spec)
    return match.group(1) if match else None


def parse_pyproject(path: Path) -> set[str]:
    deps: set[str] = set()
    try:
        data = tomllib.loads(path.read_text())
    except Exception:
        return deps
    project = data.get("project", {})
    for spec in project.get("dependencies", []) or []:
        name = dep_name(spec)
        if name:
            deps.add(name)
    for group in (project.get("optional-dependencies", {}) or {}).values():
        for spec in group or []:
            name = dep_name(spec)
            if name:
                deps.add(name)
    poetry = data.get("tool", {}).get("poetry", {})
    for name in (poetry.get("dependencies", {}) or {}):
        if name.lower() != "python":
            deps.add(name)
    for group in (poetry.get("group", {}) or {}).values():
        for name in (group.get("dependencies", {}) or {}):
            if name.lower() != "python":
                deps.add(name)
    return deps


def parse_setup_cfg(path: Path) -> set[str]:
    deps: set[str] = set()
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except Exception:
        return deps
    for section in ("options", "options.extras_require"):
        if not parser.has_section(section):
            continue
        for _, value in parser.items(section):
            for line in value.splitlines():
                name = dep_name(line)
                if name:
                    deps.add(name)
    return deps


def parse_requirements(path: Path) -> set[str]:
    deps: set[str] = set()
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except Exception:
        return deps
    for line in lines:
        name = dep_name(line)
        if name:
            deps.add(name)
    return deps


def declared_python_deps(repo: Path) -> set[str]:
    deps: set[str] = set()
    for path in repo.glob("requirements*.txt"):
        deps.update(parse_requirements(path))
    for path in repo.glob("**/requirements*.txt"):
        if ".git" not in path.parts:
            deps.update(parse_requirements(path))
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        deps.update(parse_pyproject(pyproject))
    setup_cfg = repo / "setup.cfg"
    if setup_cfg.exists():
        deps.update(parse_setup_cfg(setup_cfg))
    return deps


def _guarded_roots_in(node: ast.AST) -> set[str]:
    roots: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
            roots.add(child.module.split(".", 1)[0])
    return roots


_GUARD_HINTS = (
    "available",
    "find_spec",
    "type_checking",
    "version_info",
    "has_",
    "_installed",
    "importlib",
)


def _is_capability_guard(test: ast.AST) -> bool:
    try:
        src = ast.unparse(test).lower()
    except Exception:
        return False
    return any(hint in src for hint in _GUARD_HINTS)


def _python_records_in(node: ast.AST, path: Path, guarded: bool = False) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                records.append(
                    ImportRecord(alias.name.split(".", 1)[0], path, child.lineno, "python", guarded)
                )
        elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
            records.append(
                ImportRecord(child.module.split(".", 1)[0], path, child.lineno, "python", guarded)
            )
    return records


def import_roots_from_file(path: Path) -> tuple[set[str], set[str], list[ImportRecord]]:
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except Exception:
        return set(), set(), []
    roots: set[str] = set()
    guarded: set[str] = set()
    records = _python_records_in(tree, path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Try):
            guarded |= _guarded_roots_in(node)
        elif isinstance(node, ast.If) and _is_capability_guard(node.test):
            for branch in (node.body, node.orelse):
                for stmt in branch:
                    guarded |= _guarded_roots_in(stmt)
    return roots, guarded, records


def local_roots(repo: Path) -> set[str]:
    roots: set[str] = set()
    for path in repo.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        roots.add(path.stem)
        for parent in path.parents:
            if parent == repo:
                break
            if parent.name in SKIP_DIRS:
                break
            roots.add(parent.name)
    return roots


def imported_python(repo: Path) -> tuple[set[str], set[str], list[ImportRecord]]:
    roots: set[str] = set()
    guarded: set[str] = set()
    records: list[ImportRecord] = []
    for path in repo.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        file_roots, file_guarded, file_records = import_roots_from_file(path)
        roots.update(file_roots)
        guarded.update(file_guarded)
        records.extend(file_records)
    local = local_roots(repo)
    records = [record for record in records if record.package not in local]
    return roots - local, guarded - local, records


_JS_SPEC_RE = re.compile(
    r"""
    (?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]
    |import\s*\(\s*['"]([^'"]+)['"]\s*\)
    |require\s*\(\s*['"]([^'"]+)['"]\s*\)
    """,
    re.VERBOSE,
)


def js_package_from_spec(spec: str) -> str | None:
    spec = spec.strip()
    if not spec or spec.startswith((".", "/", "#")):
        return None
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def imported_javascript(repo: Path) -> tuple[set[str], list[ImportRecord]]:
    imports: set[str] = set()
    records: list[ImportRecord] = []
    for path in repo.rglob("*"):
        if path.suffix not in JS_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except Exception:
            continue
        for line_number, line in enumerate(lines, 1):
            for match in _JS_SPEC_RE.finditer(line):
                spec = next((group for group in match.groups() if group), "")
                package = js_package_from_spec(spec)
                if not package:
                    continue
                imports.add(package)
                records.append(ImportRecord(package, path, line_number, "javascript"))
    return imports, records


def declared_javascript_deps(repo: Path) -> set[str]:
    deps: set[str] = set()
    package_json = repo / "package.json"
    if package_json.exists():
        deps.update(_deps_from_package_json(package_json))
    for lock_name in ("package-lock.json", "npm-shrinkwrap.json"):
        lock = repo / lock_name
        if lock.exists():
            deps.update(_deps_from_package_lock(lock))
    for lock_name in ("pnpm-lock.yaml", "yarn.lock"):
        lock = repo / lock_name
        if lock.exists():
            deps.update(_deps_from_text_lock(lock))
    return deps


def _deps_from_package_json(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except Exception:
        return set()
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key, {})
        if isinstance(value, dict):
            deps.update(str(name) for name in value)
    bundled = data.get("bundledDependencies") or data.get("bundleDependencies")
    if isinstance(bundled, list):
        deps.update(str(name) for name in bundled)
    return deps


def _deps_from_package_lock(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except Exception:
        return set()
    deps: set[str] = set()
    root_deps = data.get("dependencies", {})
    if isinstance(root_deps, dict):
        deps.update(str(name) for name in root_deps)
    packages = data.get("packages", {})
    if isinstance(packages, dict):
        for key in packages:
            if not key.startswith("node_modules/"):
                continue
            package = key.removeprefix("node_modules/")
            if package:
                deps.add(package)
    return deps


_NODE_MODULES_RE = re.compile(r"node_modules/((?:@[^/\s:]+/)?[^/\s:]+)")
_LOCK_ENTRY_RE = re.compile(r"""(?m)^['"]?((?:@[^/\s:@]+/)?[^'"\s:@,]+)@""")


def _deps_from_text_lock(path: Path) -> set[str]:
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return set()
    deps: set[str] = set()
    for match in _NODE_MODULES_RE.finditer(text):
        package = js_package_from_spec(match.group(1))
        if package:
            deps.add(package)
    for match in _LOCK_ENTRY_RE.finditer(text):
        package = js_package_from_spec(match.group(1))
        if package and package not in {"version", "dependencies"}:
            deps.add(package)
    return deps


def sorted_names(names: Iterable[str]) -> list[str]:
    return sorted(set(names), key=lambda value: value.lower())
