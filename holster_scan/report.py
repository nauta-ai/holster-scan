from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable

from .detector import Finding
from .extract import ImportRecord


@dataclass(frozen=True)
class LocatedFinding:
    package: str
    reason: str
    confidence: str
    ecosystem: str
    path: str | None = None
    line: int | None = None


def locate_findings(
    root: Path,
    ecosystem: str,
    findings: Iterable[Finding],
    records: Iterable[ImportRecord],
) -> list[LocatedFinding]:
    by_package: dict[str, ImportRecord] = {}
    for record in records:
        by_package.setdefault(record.package, record)
    located: list[LocatedFinding] = []
    for finding in findings:
        record = by_package.get(finding.package)
        rel_path = None
        line = None
        if record:
            try:
                rel_path = str(record.path.resolve().relative_to(root))
            except Exception:
                rel_path = str(record.path)
            line = record.line
        located.append(
            LocatedFinding(
                package=finding.package,
                reason=finding.reason,
                confidence=finding.confidence,
                ecosystem=ecosystem,
                path=rel_path,
                line=line,
            )
        )
    return located


def render_text(findings: list[LocatedFinding]) -> str:
    if not findings:
        return "No findings."
    lines = ["Holster Scan findings:"]
    for finding in findings:
        where = ""
        if finding.path:
            where = f" ({finding.path}"
            if finding.line:
                where += f":{finding.line}"
            where += ")"
        lines.append(
            f"- [{finding.confidence}] {finding.package}{where}: {finding.reason}"
        )
    return "\n".join(lines)


def render_json(findings: list[LocatedFinding]) -> str:
    payload = {
        "summary": {
            "finding_count": len(findings),
            "high_count": sum(1 for finding in findings if finding.confidence == "high"),
            "medium_count": sum(1 for finding in findings if finding.confidence == "medium"),
        },
        "findings": [asdict(finding) for finding in findings],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_sarif(findings: list[LocatedFinding]) -> str:
    return json.dumps(build_sarif(findings), indent=2, sort_keys=True)


def build_sarif(findings: list[LocatedFinding]) -> dict:
    rule_id = "HOLSTER001"
    results = []
    for finding in findings:
        result = {
            "ruleId": rule_id,
            "level": "error" if finding.confidence == "high" else "warning",
            "message": {
                "text": f"{finding.package}: {finding.reason}",
            },
            "properties": {
                "confidence": finding.confidence,
                "ecosystem": finding.ecosystem,
                "package": finding.package,
            },
        }
        if finding.path:
            physical_location = {
                "artifactLocation": {"uri": finding.path},
            }
            if finding.line:
                physical_location["region"] = {"startLine": finding.line}
            result["locations"] = [{"physicalLocation": physical_location}]
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "holster-scan",
                        "informationUri": "https://nautaai.com",
                        "rules": [
                            {
                                "id": rule_id,
                                "name": "hallucinated-or-typosquatted-package",
                                "shortDescription": {
                                    "text": "Potential hallucinated or typosquatted package import"
                                },
                                "fullDescription": {
                                    "text": "Flags high-confidence package names that resemble AI-hallucinated dependencies or typosquats."
                                },
                                "defaultConfiguration": {"level": "error"},
                                "help": {
                                    "text": "Declare legitimate dependencies, add private-index packages to .holster.yml allow, or remove the import."
                                },
                            }
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
