"""Dependency steward — merge routine bumps, escalate the rest.

Autonomy: L3_ACT_REVERSIBLE, but the merge tool is behind ``requires_approval``
in the default mandate: a repository must explicitly lift it (see
``policies/mandates/overrides.example.yaml``). A merge is reversible (revert),
which is what makes L3 acceptable here at all.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import Field

from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import ApprovalRequired, MandateDenied, RunContext

_BOT_AUTHORS = ("dependabot[bot]", "renovate[bot]", "github-actions[bot]")
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


class StewardOutput(AgentOutput):
    """Assessment of a dependency bump."""

    package: str = ""
    from_version: str = ""
    to_version: str = ""
    bump: str = "unknown"
    """``patch`` | ``minor`` | ``major`` | ``unknown``"""
    decision: str = "review"
    """``routine`` (merge under policy) | ``review`` (a human decides)"""
    changelog_quotes: list[str] = Field(default_factory=list)
    security_fix: bool = False


class DependencySteward(Agent):
    """Assesses automated dependency updates."""

    name: ClassVar[str] = "dependency-steward"
    description: ClassVar[str] = "Merge routine dependency bumps under policy; escalate the rest"
    default_tier: ClassVar[str] = "fast"
    default_skills: ClassVar[tuple[str, ...]] = ("dependency-policy",)
    highest_risk: ClassVar[RiskClass] = RiskClass.ACT_REVERSIBLE
    output_type: ClassVar[type[AgentOutput]] = StewardOutput

    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Read the PR, its diff and CI status; classify the bump."""
        number = int(ctx.trigger.payload["number"])
        pr = ctx.tool("github.get_pr", number=number)
        if not pr.ok:
            raise RuntimeError(f"could not load PR #{number}: {pr.error}")
        self._author = pr.output["author"]
        diff = ctx.tool("github.get_pr_diff", number=number, max_chars=30_000)
        ci_ok = bool(ctx.trigger.payload.get("ci_green", False))
        self._ci_ok = ci_ok
        user = (
            f"PR #{number} '{pr.output['title']}' by {pr.output['author']}; CI green: {ci_ok}.\n\n"
            + ctx.untrusted("pr_body", pr.output["body"] or "(empty)", DataClass.INTERNAL)
            + "\n\n"
            + ctx.untrusted(
                "diff", diff.output["diff"] if diff.ok else "(unavailable)", DataClass.INTERNAL
            )
        )
        completion = ctx.llm(
            "dependency_steward",
            values={"repository": ctx.repository},
            user=user,
            schema=self.output_schema(),
            effort="low",
        )
        if completion.parsed is None:
            raise RuntimeError("the model returned no structured assessment")
        output = StewardOutput.model_validate(completion.parsed)
        output.bump = classify_bump(output.from_version, output.to_version) or output.bump
        return output

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:  # noqa: ARG002
        """Policy, as code: routine needs bot author, green CI, patch/minor, no breaking note."""
        output = expect(output, StewardOutput)
        breaking = any(
            re.search(r"break|deprecat|migrat", q, re.I) for q in output.changelog_quotes
        )
        author_ok = getattr(self, "_author", "") in _BOT_AUTHORS
        ci_ok = getattr(self, "_ci_ok", False)
        routine = output.decision == "routine"
        return [
            CheckResult(
                check="author_is_bot",
                passed=not routine or author_ok,
                detail=getattr(self, "_author", ""),
            ),
            CheckResult(
                check="ci_green",
                passed=not routine or ci_ok,
                detail="CI not green" if not ci_ok else "",
            ),
            CheckResult(
                check="bump_is_patch_or_minor",
                passed=not routine or output.bump in ("patch", "minor"),
                detail=output.bump,
            ),
            CheckResult(
                check="no_breaking_note",
                passed=not routine or not breaking,
                detail="changelog mentions breaking/deprecation/migration" if breaking else "",
            ),
        ]

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Merge routine bumps (if the mandate allows), label and comment otherwise."""
        output = expect(output, StewardOutput)
        number = int(ctx.trigger.payload["number"])
        done: dict[str, Any] = {"decision": output.decision, "bump": output.bump}
        if output.decision == "routine":
            try:
                merged = ctx.tool("github.merge_pull_request", number=number, method="squash")
                done["merge"] = merged.output
            except MandateDenied as exc:
                done["merge_denied"] = exc.reason
            except ApprovalRequired:
                ctx.tool(
                    "github.add_labels", number=number, labels=["regent:routine", "needs-approval"]
                )
                raise
        else:
            ctx.tool("github.add_labels", number=number, labels=["regent:review"])
        ctx.tool("github.comment", number=number, body=render_steward(output))
        return done


def classify_bump(old: str, new: str) -> str | None:
    """``patch`` / ``minor`` / ``major`` from two version strings, or ``None``."""
    a, b = _VERSION.search(old or ""), _VERSION.search(new or "")
    if not a or not b:
        return None
    if a.group(1) != b.group(1):
        return "major"
    if a.group(2) != b.group(2):
        return "minor"
    return "patch"


def render_steward(output: StewardOutput) -> str:
    """Markdown comment."""
    lines = [
        "## 🤖 Regent dependency steward",
        "",
        f"**{output.package or 'dependency'}** {output.from_version} → {output.to_version} "
        f"(`{output.bump}` bump) — decision: **{output.decision}**"
        + (" · 🔒 security fix" if output.security_fix else ""),
        "",
        output.summary,
    ]
    if output.changelog_quotes:
        lines += ["", "**Changelog:**", *(f"> {q}" for q in output.changelog_quotes[:6])]
    return "\n".join(lines)
