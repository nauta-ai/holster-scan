from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import ScanConfig, find_config, load_config
from .detector import detect
from .extract import EcosystemInputs, extract_project, sorted_names
from .report import LocatedFinding, locate_findings, render_json, render_sarif, render_text


CONFIDENCE_ORDER = {"medium": 1, "high": 2}


def unknown_registry(_name: str):
    return None


def unmaintained(_name: str) -> bool:
    return False


def scan_path(root: Path, config: ScanConfig, offline: bool = False) -> list[LocatedFinding]:
    project = extract_project(root)
    located: list[LocatedFinding] = []
    registry_enabled = config.registry and not offline

    for inputs in project.ecosystems:
        if not inputs.imports:
            continue
        raw_findings = _detect_for_ecosystem(inputs, registry_enabled)
        raw_findings = [finding for finding in raw_findings if not config.is_allowed(finding.package)]
        located.extend(locate_findings(project.root, inputs.ecosystem, raw_findings, inputs.records))

    return sorted(
        located,
        key=lambda finding: (
            finding.path or "",
            finding.line or 0,
            finding.package.lower(),
        ),
    )


def _detect_for_ecosystem(inputs: EcosystemInputs, registry_enabled: bool):
    registry_exists = None
    maintenance_check = None
    if not registry_enabled or inputs.ecosystem == "javascript":
        registry_exists = unknown_registry
        maintenance_check = unmaintained
    return detect(
        sorted_names(inputs.imports),
        sorted_names(inputs.declared_deps),
        optional_imports=sorted_names(inputs.optional_imports),
        registry_exists=registry_exists,
        maintenance_check=maintenance_check,
    )


def should_fail(findings: list[LocatedFinding], fail_on: str) -> bool:
    threshold = CONFIDENCE_ORDER.get(fail_on, CONFIDENCE_ORDER["high"])
    return any(CONFIDENCE_ORDER.get(finding.confidence, 0) >= threshold for finding in findings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="holster-scan")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Scan a repository path")
    scan.add_argument("path", help="Repository path to scan")
    scan.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    scan.add_argument("--config", help="Path to .holster.yml")
    scan.add_argument("--fail-on", choices=("high", "medium"), default=None)
    scan.add_argument("--offline", action="store_true", help="Disable registry lookups")
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in {"scan", "-h", "--help"}:
        argv = ["scan", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "scan":
        parser.error("unknown command")

    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"Path does not exist: {root}", file=sys.stderr)
        return 2
    root = root.resolve()
    config = load_config(find_config(root, args.config))
    fail_on = args.fail_on or config.fail_on
    findings = scan_path(root, config, offline=args.offline)

    if args.format == "json":
        print(render_json(findings))
    elif args.format == "sarif":
        print(render_sarif(findings))
    else:
        print(render_text(findings))

    return 1 if should_fail(findings, fail_on) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
