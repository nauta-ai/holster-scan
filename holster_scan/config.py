from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
import re
from typing import Any

from .detector import normalize
from .resolver import normalize_distribution


@dataclass(frozen=True)
class ScanConfig:
    allow: tuple[str, ...] = field(default_factory=tuple)
    fail_on: str = "high"
    registry: bool = True

    def is_allowed(self, package: str) -> bool:
        values = {
            package,
            package.lower(),
            normalize(package),
            normalize_distribution(package),
        }
        for pattern in self.allow:
            clean = pattern.strip()
            if not clean:
                continue
            clean_values = {
                clean,
                clean.lower(),
                normalize(clean),
                normalize_distribution(clean),
            }
            if values & clean_values:
                return True
            if any(fnmatchcase(value, clean) or fnmatchcase(value, clean.lower()) for value in values):
                return True
        return False


def find_config(repo: Path, explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None
    candidate = repo / ".holster.yml"
    return candidate if candidate.exists() else None


def load_config(path: Path | None) -> ScanConfig:
    if path is None:
        return ScanConfig()
    data = _load_yamlish(path)
    allow = tuple(str(item).strip() for item in data.get("allow", ()) if str(item).strip())
    fail_on = str(data.get("fail_on", "high")).strip().lower() or "high"
    registry_value = str(data.get("registry", "on")).strip().lower()
    registry = registry_value not in {"off", "false", "no", "0"}
    if fail_on not in {"high", "medium"}:
        fail_on = "high"
    return ScanConfig(allow=allow, fail_on=fail_on, registry=registry)


def _load_yamlish(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="ignore")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) and current_key and line.strip().startswith("-"):
            value = _clean_scalar(line.strip()[1:].strip())
            data.setdefault(current_key, []).append(value)
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if not value:
            data[current_key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[current_key] = [_clean_scalar(part.strip()) for part in inner.split(",") if part.strip()]
        else:
            data[current_key] = _clean_scalar(value)
    return data


def _clean_scalar(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^['\"]|['\"]$", "", value)
    return value
