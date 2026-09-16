"""Incident triage — hypotheses, read-only diagnostics, and a status draft.

Autonomy: L1_ADVISE. During an incident the platform's job is to make the
on-call engineer faster, not to act in their place: the agent correlates the
alert with recent changes and metrics, ranks hypotheses, proposes read-only
checks and drafts the status update. A rollback is a recommendation with its
evidence attached, executed by a human (or by a separate, gated mandate).
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import MandateDenied, RunContext

_READ_ONLY_PREFIXES = (
    "kubectl get",
    "kubectl describe",
    "kubectl logs",
    "kubectl rollout status",
    "curl -s",
    "dig",
    "promql:",
    "SELECT ",
)


class Hypothesis(BaseModel):
    """One candidate cause."""

    cause: str
    likelihood: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    would_refute: str = ""


class IncidentOutput(AgentOutput):
    """Triage result."""

    severity: str = "SEV3"
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    """Read-only commands or queries to run next."""
    recommend_rollback: bool = False
    rollback_target: str = ""
    status_update: str = ""


class IncidentTriage(Agent):
    """Correlates an alert with recent changes and proposes next steps."""

    name: ClassVar[str] = "incident-triage"
    description: ClassVar[str] = "Rank hypotheses on a firing alert and draft the status update"
    default_tier: ClassVar[str] = "deep"
    default_skills: ClassVar[tuple[str, ...]] = ("incident-communication",)
    highest_risk: ClassVar[RiskClass] = RiskClass.ADVISE
    output_type: ClassVar[type[AgentOutput]] = IncidentOutput

    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Gather alert, recent commits and a few metrics, then reason."""
        alert = ctx.trigger.payload.get("alert", {})
        parts = [ctx.untrusted("alert", _render_alert(alert), DataClass.RESTRICTED)]
        commits = ctx.tool(
            "github.list_commits", ref=str(ctx.trigger.payload.get("ref", "main")), limit=15
        )
        if commits.ok:
            parts.append(
                ctx.untrusted(
                    "recent_commits",
                    "\n".join(f"{c['sha']} {c['message']} ({c['author']})" for c in commits.output),
                    DataClass.INTERNAL,
                )
            )
        for promql in list(ctx.trigger.payload.get("queries", []))[:3]:
            try:
                result = ctx.tool("metrics.query", promql=promql)
            except MandateDenied:
                break
            if result.ok:
                parts.append(
                    ctx.untrusted(
                        f"metrics:{promql}",
                        str(result.output["results"])[:4000],
                        DataClass.INTERNAL,
                    )
                )
        completion = ctx.llm(
            "incident_triage",
            values={"repository": ctx.repository, "environment": ctx.environment},
            user="\n\n".join(parts),
            schema=self.output_schema(),
            effort="high",
        )
        if completion.parsed is None:
            raise RuntimeError("the model returned no structured triage")
        return IncidentOutput.model_validate(completion.parsed)

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:  # noqa: ARG002
        """Diagnostics must be read-only; hypotheses must carry evidence."""
        output = expect(output, IncidentOutput)
        unsafe = [d for d in output.diagnostics if not d.strip().startswith(_READ_ONLY_PREFIXES)]
        without_evidence = [h.cause for h in output.hypotheses if not h.supporting_evidence]
        return [
            CheckResult(
                check="diagnostics_read_only",
                passed=not unsafe,
                detail=f"not read-only: {unsafe}" if unsafe else "",
            ),
            CheckResult(
                check="hypotheses_have_evidence",
                passed=not without_evidence,
                detail=f"no evidence: {without_evidence}" if without_evidence else "",
            ),
            CheckResult(
                check="severity_known",
                passed=output.severity in ("SEV1", "SEV2", "SEV3"),
                detail=output.severity,
            ),
        ]

    def verification_focus(self) -> str:
        """What the critic looks for on incidents."""
        return (
            "speculation presented as fact in the status update, a rollback recommended without "
            "a matching recent change, and diagnostics that would change state"
        )

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Post the triage on the incident issue (or open one)."""
        output = expect(output, IncidentOutput)
        body = render_incident(output)
        issue_number = ctx.trigger.payload.get("issue_number")
        if issue_number:
            posted = ctx.tool("github.comment", number=int(issue_number), body=body)
            return {"comment": posted.output}
        alert = ctx.trigger.payload.get("alert", {})
        created = ctx.tool(
            "github.create_issue",
            title=f"[{output.severity}] {alert.get('name', 'incident')}",
            body=body,
            labels=["incident", output.severity.lower()],
        )
        return {"issue": created.output}


def _render_alert(alert: dict[str, Any]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in sorted(alert.items())) or "(no alert payload)"


def render_incident(output: IncidentOutput) -> str:
    """Markdown for the incident issue."""
    lines = [f"## 🤖 Regent incident triage — {output.severity}", "", output.summary, ""]
    lines.append("**Hypotheses (ranked):**")
    for i, h in enumerate(sorted(output.hypotheses, key=lambda x: -x.likelihood), start=1):
        lines.append(f"{i}. ({h.likelihood:.0%}) {h.cause}")
        for e in h.supporting_evidence[:3]:
            lines.append(f"   - evidence: {e}")
        if h.would_refute:
            lines.append(f"   - would refute: {h.would_refute}")
    if output.diagnostics:
        lines += [
            "",
            "**Read-only diagnostics to run next:**",
            *(f"- `{d}`" for d in output.diagnostics),
        ]
    if output.recommend_rollback:
        lines += [
            "",
            f"⚠️ **Rollback recommended** to `{output.rollback_target or 'previous release'}` — "
            "a human executes it; this agent cannot.",
        ]
    if output.status_update:
        lines += ["", "**Draft status update:**", "", f"> {output.status_update}"]
    return "\n".join(lines)
