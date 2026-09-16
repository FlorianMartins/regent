"""PR reviewer — advisory review of a pull request, posted as a GitHub review.

Autonomy: L1_ADVISE. It reads the diff, produces findings that each cite a
file and line, and posts them as *comments*. It never approves and never
requests changes: the merge decision stays with humans and branch protection.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import RunContext


class Finding(BaseModel):
    """One review finding."""

    file: str
    line: int = Field(ge=1)
    severity: str
    category: str
    title: str
    detail: str
    quote: str = ""
    suggestion: str = ""


class ReviewOutput(AgentOutput):
    """Structured review."""

    findings: list[Finding] = Field(default_factory=list)
    diff_truncated: bool = False


_SEVERITIES = ("critical", "high", "medium", "low")
_CATEGORIES = ("correctness", "security", "reliability", "maintainability", "tests")


class PRReviewer(Agent):
    """Reviews a pull request and posts advisory findings."""

    name: ClassVar[str] = "pr-reviewer"
    description: ClassVar[str] = (
        "Advisory code review of a pull request with line-anchored findings"
    )
    default_tier: ClassVar[str] = "balanced"
    default_skills: ClassVar[tuple[str, ...]] = ("secure-review",)
    highest_risk: ClassVar[RiskClass] = RiskClass.ADVISE
    output_type: ClassVar[type[AgentOutput]] = ReviewOutput

    def __init__(self) -> None:
        self._diff_files: set[str] = set()

    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Fetch the PR and its diff, ask the model for line-anchored findings."""
        number = int(ctx.trigger.payload["number"])
        pr = ctx.tool("github.get_pr", number=number)
        diff = ctx.tool("github.get_pr_diff", number=number)
        if not pr.ok or not diff.ok:
            raise RuntimeError(f"could not load PR #{number}: {pr.error or diff.error}")
        meta = pr.output
        user = (
            f"Pull request #{number}: {meta['title']} by {meta['author']} "
            f"({meta['head']} → {meta['base']}, {meta['changed_files']} files, "
            f"+{meta['additions']}/-{meta['deletions']}).\n\n"
            + ctx.untrusted("pr_description", meta["body"] or "(empty)", DataClass.INTERNAL)
            + "\n\n"
            + ctx.untrusted("diff", diff.output["diff"], DataClass.CONFIDENTIAL)
        )
        completion = ctx.llm(
            "pr_reviewer",
            values={"repository": ctx.repository},
            user=user,
            schema=self.output_schema(),
            effort="high",
        )
        if completion.parsed is None:
            raise RuntimeError("the model returned no structured review")
        output = ReviewOutput.model_validate(completion.parsed)
        output.diff_truncated = bool(diff.output.get("truncated"))
        self._diff_files = _files_in_diff(diff.output["diff"])
        return output

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:  # noqa: ARG002
        """Every finding must point at a file that is in the diff and use known enums."""
        output = expect(output, ReviewOutput)
        results: list[CheckResult] = []
        diff_files = self._diff_files
        bad_files = [f.file for f in output.findings if diff_files and f.file not in diff_files]
        results.append(
            CheckResult(
                check="findings_cite_lines",
                passed=not bad_files,
                detail=f"files not in diff: {sorted(set(bad_files))}" if bad_files else "",
            )
        )
        bad_enum = [
            f.title
            for f in output.findings
            if f.severity not in _SEVERITIES or f.category not in _CATEGORIES
        ]
        results.append(
            CheckResult(
                check="findings_use_known_enums",
                passed=not bad_enum,
                detail=f"invalid severity/category on: {bad_enum}" if bad_enum else "",
            )
        )
        return results

    def verification_focus(self) -> str:
        """What the critic should focus on for reviews."""
        return (
            "findings that do not quote real lines of the diff, severities that overstate "
            "the impact, and anything phrased as an approval or a merge decision"
        )

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Post the review (COMMENT event only) with inline comments."""
        output = expect(output, ReviewOutput)
        number = int(ctx.trigger.payload["number"])
        body = render_review(output)
        comments = [
            {
                "path": f.file,
                "line": f.line,
                "body": f"**{f.severity.upper()} · {f.category}** — {f.title}\n\n{f.detail}"
                + (f"\n\n```suggestion\n{f.suggestion}\n```" if f.suggestion else ""),
            }
            for f in output.findings
        ]
        result = ctx.tool("github.create_review", number=number, body=body, comments=comments)
        labels = sorted(
            {f"regent:{f.severity}" for f in output.findings if f.severity in ("critical", "high")}
        )
        if labels:
            ctx.tool("github.add_labels", number=number, labels=labels)
        return {"review": result.output, "findings": len(output.findings), "labels": labels}


def render_review(output: ReviewOutput) -> str:
    """Markdown body of the review."""
    counts = {s: sum(1 for f in output.findings if f.severity == s) for s in _SEVERITIES}
    header = " · ".join(f"{n} {s}" for s, n in counts.items() if n) or "no finding"
    lines = [
        "## 🤖 Regent review — advisory",
        "",
        output.summary,
        "",
        f"**Findings:** {header}",
    ]
    if output.diff_truncated:
        lines.append("\n> ⚠️ The diff was truncated; large files were only partially reviewed.")
    lines.append(
        f"\n<sub>Confidence {output.confidence:.0%}. This review is advisory: it never approves "
        "or blocks. Every finding is anchored to a line; reply to dismiss with a reason.</sub>"
    )
    return "\n".join(lines)


def _files_in_diff(diff: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)}
