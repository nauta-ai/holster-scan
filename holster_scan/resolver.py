"""Resolve Python import module names to likely distribution names."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Iterable


@lru_cache(maxsize=8192)
def exists_on_registry(name: str, timeout: float = 4.0):
    """Does this package exist on PyPI? True=exists (legit, suppress), False=404
    (likely slopsquat/hallucinated), None=unknown (network/error - caller should
    NOT suppress on None). This is the oracle that separates a real-but-undeclared
    import (cohere -> 200) from a hallucination (reqeusts -> 404)."""
    pkg = (name or "").strip()
    if not pkg:
        return None
    url = "https://pypi.org/pypi/%s/json" % urllib.parse.quote(pkg, safe="")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "holster-scan/0.0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except Exception:
        return None


# "Now" for maintenance recency. The fleet's clock is the source of truth; a
# package whose newest release is within ~2 years is treated as actively
# maintained. Bump CURRENT_YEAR if this probe is revisited in a later year.
CURRENT_YEAR = 2026
MAINTAINED_WITHIN_YEARS = 2
MIN_RELEASES_FOR_MAINTAINED = 3


@lru_cache(maxsize=8192)
def pypi_maintenance(name: str, timeout: float = 5.0):
    """(release_count, last_upload_year) for a PyPI package, or (None, None) if
    it doesn't exist / can't be read. Used to tell a real, actively-maintained
    look-alike (psycopg, uuid-utils) from an abandoned published typosquat
    (panda last shipped 2015, django-utils 2010)."""
    import json as _json
    pkg = (name or "").strip()
    if not pkg:
        return None, None
    url = "https://pypi.org/pypi/%s/json" % urllib.parse.quote(pkg, safe="")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "holster-scan/0.0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = _json.load(r)
    except Exception:
        return None, None
    releases = data.get("releases", {}) or {}
    years = [
        f["upload_time"][:4]
        for files in releases.values()
        for f in files
        if f.get("upload_time")
    ]
    last_year = max((int(y) for y in years if y.isdigit()), default=None)
    return len(releases), last_year


def is_maintained(name: str) -> bool:
    """True when a package looks actively maintained (recent release + a real
    release history). None/unknown -> False (do not vouch for it)."""
    count, last_year = pypi_maintenance(name)
    if not count or last_year is None:
        return False
    return (
        count >= MIN_RELEASES_FOR_MAINTAINED
        and last_year >= CURRENT_YEAR - MAINTAINED_WITHIN_YEARS
    )


STDLIB_FALLBACK = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "bdb", "bisect",
    "bz2", "calendar", "cmath", "cmd", "code", "codecs", "collections",
    "concurrent", "configparser", "contextlib", "copy", "copyreg", "csv",
    "ctypes", "dataclasses", "datetime", "decimal", "difflib", "dis",
    "email", "enum", "errno", "faulthandler", "fnmatch", "fractions",
    "functools", "gc", "getopt", "getpass", "gettext", "glob", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "linecache", "locale",
    "logging", "lzma", "math", "mimetypes", "multiprocessing", "netrc",
    "operator", "optparse", "os", "pathlib", "pickle", "pkgutil",
    "platform", "plistlib", "pprint", "profile", "pstats", "pwd", "py_compile",
    "queue", "random", "re", "readline", "reprlib", "resource", "secrets",
    "select", "selectors", "shelve", "shlex", "shutil", "signal", "site",
    "socket", "sqlite3", "ssl", "stat", "statistics", "string",
    "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
    "sysconfig", "tarfile", "tempfile", "textwrap", "threading", "time",
    "timeit", "tkinter", "token", "tokenize", "traceback", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "xml", "xmlrpc", "zipapp", "zipfile",
    "zipimport", "zlib",
}

STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", STDLIB_FALLBACK)) | {
    "__future__",
}


# Curated common import-root to PyPI distribution aliases. Keys are import names,
# values are distribution names a project may declare.
IMPORT_TO_DISTRIBUTIONS = {
    "PIL": {"Pillow"},
    "OpenSSL": {"pyOpenSSL"},
    "Bio": {"biopython"},
    "Crypto": {"pycryptodome", "pycrypto"},
    "Cython": {"Cython"},
    "IPython": {"ipython"},
    "MySQLdb": {"mysqlclient"},
    "Pygments": {"Pygments"},
    "Tkinter": {"tk"},
    "attr": {"attrs"},
    "bcrypt": {"bcrypt"},
    "bs4": {"beautifulsoup4"},
    "cairo": {"pycairo"},
    "click": {"click"},
    "cv2": {"opencv-python", "opencv-contrib-python", "opencv-python-headless"},
    "dateutil": {"python-dateutil"},
    "dns": {"dnspython"},
    "dotenv": {"python-dotenv"},
    "fitz": {"PyMuPDF"},
    "fla": {"flash-linear-attention"},
    "git": {"GitPython"},
    "googleapiclient": {"google-api-python-client"},
    "grpc": {"grpcio"},
    "httplib2": {"httplib2"},
    "imblearn": {"imbalanced-learn"},
    "lavis": {"salesforce-lavis"},
    "jinja2": {"Jinja2"},
    "jwt": {"PyJWT"},
    "magic": {"python-magic"},
    "mpl_toolkits": {"matplotlib"},
    "multipart": {"python-multipart"},
    "mysql": {"mysql-connector-python", "mysqlclient"},
    "nacl": {"PyNaCl"},
    "olefile": {"olefile"},
    "pandas": {"pandas"},
    "pkg_resources": {"setuptools"},
    "psycopg2": {"psycopg2", "psycopg2-binary"},
    "pyarrow": {"pyarrow"},
    "pycurl": {"pycurl"},
    "pydantic": {"pydantic"},
    "pygments": {"Pygments"},
    "pymongo": {"pymongo"},
    "pymysql": {"PyMySQL"},
    "pytest": {"pytest"},
    "requests": {"requests"},
    "ruamel": {"ruamel.yaml"},
    "scipy": {"scipy"},
    "skimage": {"scikit-image"},
    "sklearn": {"scikit-learn"},
    "sqlalchemy": {"SQLAlchemy"},
    "tensorflow": {"tensorflow", "tensorflow-cpu", "tensorflow-macos"},
    "torch": {"torch"},
    "typing_extensions": {"typing-extensions"},
    "uvicorn": {"uvicorn"},
    "vcr": {"vcrpy"},
    "werkzeug": {"Werkzeug"},
    "yaml": {"PyYAML"},
    "zmq": {"pyzmq"},
    "zope": {"zope.interface", "zope.event"},
}


@dataclass(frozen=True)
class ResolvedImport:
    import_name: str
    root_module: str
    distributions: frozenset[str]
    is_stdlib: bool


def normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).strip("-").lower()


def import_root(name: str) -> str:
    return name.strip().split(".", 1)[0]


@lru_cache(maxsize=1)
def installed_packages_distributions() -> dict[str, tuple[str, ...]]:
    try:
        mapping = importlib.metadata.packages_distributions()
    except Exception:
        return {}
    return {module: tuple(dists) for module, dists in mapping.items()}


def resolve_import(import_name: str) -> ResolvedImport:
    root = import_root(import_name)
    distributions: set[str] = set()

    if root in IMPORT_TO_DISTRIBUTIONS:
        distributions.update(IMPORT_TO_DISTRIBUTIONS[root])

    installed = installed_packages_distributions()
    distributions.update(installed.get(root, ()))

    # Identity remains a useful fallback because many distributions expose an
    # import root with the same normalized name.
    distributions.add(root)

    return ResolvedImport(
        import_name=import_name,
        root_module=root,
        distributions=frozenset(distributions),
        is_stdlib=root in STDLIB_MODULES,
    )


def declared_dependency_names(declared_deps: Iterable[str]) -> set[str]:
    return {normalize_distribution(dep) for dep in declared_deps if dep and dep.strip()}


def is_declared_import(import_name: str, declared_deps: Iterable[str]) -> bool:
    declared = declared_dependency_names(declared_deps)
    if not declared:
        return False
    resolved = resolve_import(import_name)
    if resolved.is_stdlib:
        return True
    return any(normalize_distribution(dist) in declared for dist in resolved.distributions)
