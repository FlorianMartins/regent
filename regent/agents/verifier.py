"""The independent critic.

Every output that could lead to an action is reviewed twice:

* by **deterministic checks** the agent declares (does the fix still scan
  clean? does the patch touch only the files it claims?), and
* by a **second LLM call with a different prompt** whose only job is to find
  what is wrong with the output, given the same evidence.

The critic never *fixes* anything: it accepts or rejects, with reasons that go
to the ledger. Separation of duties, applied to language models.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from regent.agents.base import Agent, AgentOutput, CheckResult
from regent.core.models import DataClass
from regent.observability import metrics
from regent.runtime.context import RunContext


class Verdict(BaseModel):
    """What the verifier concluded."""

    accepted: bool
    issues: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    critic_confidence: float = 0.0
    skipped: bool = False
    """True when the mandate asked for no verification."""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view."""
        return self.model_dump(mode="json")


class CriticAnswer(BaseModel):
    """Structured output of the critic prompt."""

    accept: bool
    issues: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


def verify(agent: Agent, output: AgentOutput, ctx: RunContext) -> Verdict:
    """Run the checks and the critic under the run's mandate."""
    mode = ctx.mandate.verification
    if mode == "none":
        verdict = Verdict(accepted=True, skipped=True)
        ctx.record("verification", {"mode": mode, **verdict.as_dict()})
        return verdict

    checks = agent.checks(output, ctx)
    failed = [c for c in checks if not c.passed]

    evidence = "\n".join(f"- {line}" for line in output.evidence) or "- (none provided)"
    tool_digest = "\n".join(
        f"- {r.tool}: {'ok' if r.ok else 'FAILED ' + str(r.error)}" for r in ctx.tool_results[-20:]
    )
    user = (
        "Review the proposed output below. Reject it if any claim lacks evidence, if it "
        "would do more than the intent states, or if a deterministic check failed.\n\n"
        f"Focus: {agent.verification_focus()}\n\n"
        f"Deterministic checks:\n{_render_checks(checks)}\n\n"
        f"Tools that were called:\n{tool_digest or '- (none)'}\n\n"
        + ctx.untrusted(
            "proposed_output", json.dumps(output.as_dict(), indent=2), DataClass.INTERNAL
        )
        + "\n\n"
        + ctx.untrusted("evidence", evidence, ctx.highest_classification)
    )
    schema = CriticAnswer.model_json_schema()
    schema.pop("title", None)
    schema["additionalProperties"] = False
    completion = ctx.llm(
        "verifier",
        values={"agent": agent.name, "agent_description": agent.description},
        user=user,
        schema=schema,
        tier=_critic_tier(ctx.mandate.model_tier),
        effort="high",
        max_output_tokens=2_000,
    )
    issues: list[str] = [f"check failed: {c.check} — {c.detail}" for c in failed]
    confidence = 0.0
    accepted_by_critic = False
    if completion.parsed is not None and not completion.refused:
        try:
            answer = CriticAnswer.model_validate(completion.parsed)
        except ValueError:
            issues.append("critic returned an unreadable answer")
        else:
            accepted_by_critic = answer.accept
            issues.extend(answer.issues)
            confidence = answer.confidence
    else:
        issues.append("critic produced no structured answer")

    accepted = accepted_by_critic and not failed
    verdict = Verdict(accepted=accepted, issues=issues, checks=checks, critic_confidence=confidence)
    metrics.VERIFICATIONS_TOTAL.labels(agent.name, "accepted" if accepted else "rejected").inc()
    ctx.record("verification", {"mode": mode, **verdict.as_dict()})
    return verdict


def _render_checks(checks: list[CheckResult]) -> str:
    if not checks:
        return "- (the agent declares no deterministic checks)"
    return "\n".join(
        f"- {'PASS' if c.passed else 'FAIL'} {c.check}: {c.detail or ''}".rstrip() for c in checks
    )


def _critic_tier(tier: str) -> str:
    """The critic is at least as capable as the author; never cheaper."""
    return {"fast": "balanced", "balanced": "balanced", "deep": "deep"}.get(tier, "balanced")
