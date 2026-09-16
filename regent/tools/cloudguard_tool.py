"""CloudGuard-IaC as a tool: deterministic security findings for the agents.

The scanner is the *ground truth* the IaC guardian works from and verifies
against: an LLM proposes a fix, CloudGuard says whether the finding is gone.
Nothing an LLM says about security is trusted without this second opinion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from regent.core.models import DataClass, RiskClass
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec


def scan(paths: list[str], workspace: Path, ignore: list[str] | None = None) -> dict[str, Any]:
    """Run CloudGuard on *paths* (relative to *workspace*) and normalise the result."""
    from cloudguard.engine import scan_paths

    targets = [workspace / p for p in paths] or [workspace]
    result = scan_paths(targets, ignore=ignore or [], root=workspace)
    findings = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity.value,
            "file": f.file,
            "line": f.line,
            "resource": f.resource,
            "message": f.message,
            "title": f.title,
            "why": f.why,
            "remediation": f.remediation,
        }
        for f in result.sorted_findings()
    ]
    counts = {sev.value: n for sev, n in result.counts().items()}
    return {
        "findings": findings,
        "counts": counts,
        "total": len(findings),
        "files_scanned": result.files_scanned,
        "tool_version": result.tool_version,
    }


def register_cloudguard_tools(registry: ToolRegistry) -> None:
    """Register ``cloudguard.scan``."""

    def _scan(a: dict[str, Any], ctx: ToolContext) -> Any:
        return scan(list(a.get("paths", [])), ctx.workspace, list(a.get("ignore", [])))

    registry.register(
        FunctionTool(
            ToolSpec(
                name="cloudguard.scan",
                description="Scan Terraform and Dockerfiles for misconfigurations (CloudGuard-IaC)",
                risk=RiskClass.READ,
                classification=DataClass.INTERNAL,
                parameters={
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "ignore": {"type": "array", "items": {"type": "string"}},
                    },
                },
            ),
            _scan,
        )
    )
