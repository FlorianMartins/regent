"""CI triage — classify a failed workflow run and take the smallest safe step.

Autonomy: up to L3_ACT_REVERSIBLE. Re-running failed jobs is reversible and
cheap; it is the only action the agent takes on its own, and only when the
evidence says "flaky" or "infrastructure". Everything else becomes a comment
or an issue for a human.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import MandateDenied, RunContext

CATEGORIES = ("flaky", "infrastructure", "dependency", "code", "config", "unknown")
RERUNNABLE = ("flaky", "infrastructure")


class TriageOutput(AgentOutput):
    """Classification of a failed run."""

    category: str
    failed_jobs: list[str] = Field(default_factory=list)
    root_cause: str = ""
    log_quotes: list[str] = Field(default_factory=list)
    recommend_rerun: bool = False
    suggested_fix: str = ""


class CITriage(Agent):
    """Classifies CI failures and re-runs the flaky ones."""

    name: ClassVar[str] = "ci-triage"
    description: ClassVar[str] = (
        "Classify a failed CI run; re-run flaky jobs, escalate real failures"
    )
    default_tier: ClassVar[str] = "balanced"
    highest_risk: ClassVar[RiskClass] = RiskClass.ACT_REVERSIBLE
    output_type: ClassVar[type[AgentOutput]] = TriageOutput

    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Load the run, the tail of each failed job's logs, and classify."""
        run_id = int(ctx.trigger.payload["run_id"])
        run = ctx.tool("github.get_workflow_run", run_id=run_id)
        if not run.ok:
            raise RuntimeError(f"could not load workflow run {run_id}: {run.error}")
        failed = [j for j in run.output["jobs"] if j.get("conclusion") == "failure"]
        logs: list[str] = []
        for job in failed[:3]:
            tail = ctx.tool("github.get_job_logs", job_id=job["id"], max_chars=20_000)
            if tail.ok:
                logs.append(
                    ctx.untrusted(
                        f"job_log:{job['name']}", tail.output["logs"], DataClass.CONFIDENTIAL
                    )
                )
        user = (
            f"Workflow '{run.output.get('name')}' run {run_id} on branch "
            f"{run.output.get('head_branch')} (attempt {run.output.get('run_attempt')}, "
            f"event {run.output.get('event')}) failed.\n"
            f"Failed jobs: {', '.join(j['name'] for j in failed) or 'none reported'}.\n\n"
            + "\n\n".join(logs)
        )
        completion = ctx.llm(
            "ci_triage",
            values={"repository": ctx.repository},
            user=user,
            schema=self.output_schema(),
            effort="medium",
        )
        if completion.parsed is None:
            raise RuntimeError("the model returned no structured triage")
        output = TriageOutput.model_validate(completion.parsed)
        output.failed_jobs = [j["name"] for j in failed]
        self._attempt = int(run.output.get("run_attempt", 1))
        return output

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:  # noqa: ARG002
        """A re-run needs a re-runnable category, quotes, and no previous re-run."""
        output = expect(output, TriageOutput)
        attempt = getattr(self, "_attempt", 1)
        return [
            CheckResult(
                check="category_known",
                passed=output.category in CATEGORIES,
                detail=output.category,
            ),
            CheckResult(
                check="classification_has_quotes",
                passed=output.category == "unknown" or bool(output.log_quotes),
                detail="no log line quoted" if not output.log_quotes else "",
            ),
            CheckResult(
                check="rerun_only_when_flaky",
                passed=not output.recommend_rerun or output.category in RERUNNABLE,
                detail=f"category {output.category} does not justify a re-run",
            ),
            CheckResult(
                check="rerun_at_most_once",
                passed=not output.recommend_rerun or attempt < 2,
                detail=f"already at attempt {attempt}" if attempt >= 2 else "",
            ),
        ]

    def verification_focus(self) -> str:
        """What the critic looks for on CI triage."""
        return (
            "a 'flaky' verdict without evidence of intermittence, a re-run recommended for a "
            "code failure, and root causes not present in the quoted logs"
        )

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Re-run when justified (if the mandate allows), otherwise comment or open an issue."""
        output = expect(output, TriageOutput)
        run_id = int(ctx.trigger.payload["run_id"])
        done: dict[str, Any] = {"category": output.category}
        if output.recommend_rerun:
            try:
                rerun = ctx.tool("github.rerun_failed_jobs", run_id=run_id)
                done["rerun"] = rerun.output
            except MandateDenied as exc:
                done["rerun_denied"] = exc.reason
        if output.category in ("code", "dependency", "config"):
            issue = ctx.tool(
                "github.create_issue",
                title=f"CI failure ({output.category}): {output.root_cause[:80] or 'see logs'}",
                body=render_triage(output, run_id),
                labels=["ci-failure", f"regent:{output.category}"],
            )
            done["issue"] = issue.output
        pr_number = ctx.trigger.payload.get("pr_number")
        if pr_number:
            comment = ctx.tool(
                "github.comment", number=int(pr_number), body=render_triage(output, run_id)
            )
            done["comment"] = comment.output
        return done


def render_triage(output: TriageOutput, run_id: int) -> str:
    """Markdown for the comment or the issue."""
    quotes = "\n".join(f"> {q}" for q in output.log_quotes[:8])
    lines = [
        f"## 🤖 Regent CI triage — run {run_id}",
        "",
        f"**Category:** `{output.category}` · **Confidence:** {output.confidence:.0%}",
        f"**Failed jobs:** {', '.join(output.failed_jobs) or '—'}",
        "",
        output.summary,
        "",
        f"**Root cause:** {output.root_cause or 'not determined'}",
    ]
    if quotes:
        lines += ["", "**Evidence from the logs:**", quotes]
    if output.suggested_fix:
        lines += ["", f"**Suggested fix:** {output.suggested_fix}"]
    if output.recommend_rerun:
        lines += ["", "🔁 The failed jobs were re-run once (reversible action under mandate)."]
    return "\n".join(lines)
