"""IaC guardian — turn CloudGuard findings into a fix pull request.

Autonomy: L2_PROPOSE. The agent scans, asks the model for minimal fixes,
writes them to a branch of the workspace, **re-scans** to prove each finding
is gone, and opens a *draft* pull request. It cannot merge. CloudGuard, not
the model, decides whether the fix worked.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import RunContext

FIXABLE_SEVERITIES = ("CRITICAL", "HIGH")


class FileChange(BaseModel):
    """Full new content of one file."""

    path: str
    content: str
    resolves: list[str] = Field(default_factory=list)
    """Rule ids (``CG_IAC_001``) this change is meant to resolve."""


class GuardianOutput(AgentOutput):
    """Proposed remediation."""

    changes: list[FileChange] = Field(default_factory=list)
    left_open: list[str] = Field(default_factory=list)
    """Findings the agent could not fix safely, with the reason in ``summary``."""


class IaCGuardian(Agent):
    """Fixes CloudGuard findings and proposes them as a draft PR."""

    name: ClassVar[str] = "iac-guardian"
    description: ClassVar[str] = "Propose minimal fixes for Terraform/Dockerfile security findings"
    default_tier: ClassVar[str] = "deep"
    default_skills: ClassVar[tuple[str, ...]] = ("terraform-baseline",)
    highest_risk: ClassVar[RiskClass] = RiskClass.PROPOSE
    output_type: ClassVar[type[AgentOutput]] = GuardianOutput

    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Scan, load the offending files, ask for minimal full-file fixes."""
        paths = list(ctx.trigger.payload.get("paths", ["."]))
        scan = ctx.tool("cloudguard.scan", paths=paths)
        if not scan.ok:
            raise RuntimeError(f"CloudGuard failed: {scan.error}")
        findings = [f for f in scan.output["findings"] if f["severity"] in FIXABLE_SEVERITIES]
        self._before = scan.output
        self._targets = findings
        if not findings:
            return GuardianOutput(
                summary="No CRITICAL or HIGH finding: nothing to fix.",
                confidence=1.0,
                evidence=[f"cloudguard {scan.output['tool_version']}: {scan.output['counts']}"],
            )
        files = sorted({f["file"] for f in findings})
        blobs: list[str] = []
        for path in files[:8]:
            content = ctx.tool("fs.read", path=path)
            if content.ok:
                blobs.append(
                    ctx.untrusted(f"file:{path}", content.output["content"], DataClass.CONFIDENTIAL)
                )
        rendered = "\n".join(
            f"- {f['rule_id']} {f['severity']} {f['file']}:{f['line']} ({f['resource']}): "
            f"{f['message']}\n  why: {f['why']}\n  fix: {f['remediation']}"
            for f in findings
        )
        user = (
            f"Findings to fix ({len(findings)}):\n"
            + ctx.untrusted("cloudguard_findings", rendered, DataClass.INTERNAL)
            + "\n\nFiles:\n"
            + "\n\n".join(blobs)
        )
        completion = ctx.llm(
            "iac_guardian",
            values={"repository": ctx.repository},
            user=user,
            schema=self.output_schema(),
            effort="high",
            max_output_tokens=16_000,
        )
        if completion.parsed is None:
            raise RuntimeError("the model returned no structured remediation")
        output = GuardianOutput.model_validate(completion.parsed)
        output.evidence.append(f"before: {scan.output['counts']}")
        return output

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:
        """Write the proposed files to the workspace and re-scan: findings must be gone."""
        output = expect(output, GuardianOutput)
        results: list[CheckResult] = []
        targets = getattr(self, "_targets", [])
        allowed_files = {f["file"] for f in targets}
        stray = [c.path for c in output.changes if c.path not in allowed_files]
        results.append(
            CheckResult(
                check="changes_only_flagged_files",
                passed=not stray,
                detail=f"unexpected files: {stray}" if stray else "",
            )
        )
        if not output.changes:
            results.append(
                CheckResult(
                    check="cloudguard_clean_after_fix",
                    passed=not targets,
                    detail="no change proposed" if targets else "",
                )
            )
            return results
        ctx.set_phase_gate(RiskClass.PROPOSE)  # writing to the workspace is a proposal
        for change in output.changes:
            ctx.tool("fs.write", path=change.path, content=change.content)
        after = ctx.tool("cloudguard.scan", paths=sorted({c.path for c in output.changes}))
        remaining = (
            [f for f in after.output["findings"] if f["severity"] in FIXABLE_SEVERITIES]
            if after.ok
            else None
        )
        claimed = {rule for c in output.changes for rule in c.resolves}
        still_there = (
            sorted({f["rule_id"] for f in remaining or []} & claimed)
            if remaining is not None
            else None
        )
        results.append(
            CheckResult(
                check="cloudguard_clean_after_fix",
                passed=after.ok and not still_there,
                detail=(
                    f"still failing after fix: {still_there}"
                    if still_there
                    else ("re-scan failed" if not after.ok else "")
                ),
            )
        )
        self._after = after.output if after.ok else None
        return results

    def verification_focus(self) -> str:
        """What the critic looks for on IaC fixes."""
        return (
            "controls weakened instead of fixed, `cloudguard:ignore` comments without a stated "
            "exception, hard-coded values the agent could not know, and unrelated edits"
        )

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Open a draft PR from the branch the CI job pushed (or describe it in dry run)."""
        output = expect(output, GuardianOutput)
        if not output.changes:
            return {"pull_request": None, "reason": "nothing to fix"}
        head = str(ctx.trigger.payload.get("head", f"regent/iac-fix-{ctx.run_id[:8]}"))
        base = str(ctx.trigger.payload.get("base", "main"))
        pr = ctx.tool(
            "github.create_pull_request",
            title=f"sec(iac): fix {len(output.changes)} CloudGuard finding(s)",
            body=render_pr_body(
                output, getattr(self, "_before", {}), getattr(self, "_after", None)
            ),
            head=head,
            base=base,
            draft=True,
        )
        return {"pull_request": pr.output, "changes": [c.path for c in output.changes]}


def render_pr_body(
    output: GuardianOutput, before: dict[str, Any], after: dict[str, Any] | None
) -> str:
    """Markdown body of the fix PR."""
    lines = [
        "## 🤖 Regent IaC guardian — proposed remediation",
        "",
        output.summary,
        "",
        "| | CloudGuard findings |",
        "|---|---|",
        f"| before | `{before.get('counts', {})}` |",
        f"| after  | `{after.get('counts', {}) if after else 'not re-scanned'}` |",
        "",
        "**Changes:**",
        *(f"- `{c.path}` resolves {', '.join(c.resolves) or '—'}" for c in output.changes),
    ]
    if output.left_open:
        lines += ["", "**Left open (needs a human):**", *(f"- {item}" for item in output.left_open)]
    lines += [
        "",
        "<sub>Draft PR opened under an L2_PROPOSE mandate. CloudGuard re-scanned the result; "
        "a human reviews and merges.</sub>",
    ]
    return "\n".join(lines)
