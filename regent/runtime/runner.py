"""The runner: one agent, one mandate, one run — analyse, verify, act.

`Platform` wires the collaborators once (providers, tools, prompts, skills,
mandates, ledger); `Runner` executes a single run and returns a `RunRecord`
whatever happens. Exceptions are outcomes here, not crashes: a denied tool
call is a *result* the caller can display and audit.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from regent.agents.base import Agent
from regent.agents.verifier import verify
from regent.core.budget import BudgetExceeded
from regent.core.ledger import Ledger
from regent.core.models import Mandate, RiskClass, RunRecord, RunStatus, Trigger
from regent.core.policy import MandateStore
from regent.gateway.gateway import ConfidentialityViolation, Gateway
from regent.gateway.prompts import PromptRegistry
from regent.gateway.providers import ProviderError
from regent.observability import metrics
from regent.observability.tracing import span
from regent.runtime.context import ApprovalRequired, MandateDenied, RunContext
from regent.skills import SkillRegistry
from regent.tools.base import ToolRegistry

log = logging.getLogger("regent.runner")


class Platform:
    """Long-lived wiring shared by every run."""

    def __init__(
        self,
        *,
        gateway: Gateway,
        tools: ToolRegistry,
        mandates: MandateStore,
        ledger: Ledger,
        prompts: PromptRegistry | None = None,
        skills: SkillRegistry | None = None,
        agents: Iterable[Agent] = (),
    ) -> None:
        self.gateway = gateway
        self.tools = tools
        self.mandates = mandates
        self.ledger = ledger
        self.prompts = prompts or PromptRegistry()
        self.skills = skills or SkillRegistry()
        self.agents: dict[str, Agent] = {a.name: a for a in agents}

    def register(self, agent: Agent) -> None:
        """Add an agent to the catalogue."""
        self.agents[agent.name] = agent


class Runner:
    """Executes runs on a platform."""

    def __init__(self, platform: Platform) -> None:
        self._p = platform

    def run(
        self,
        agent_name: str,
        *,
        repository: str,
        environment: str = "dev",
        trigger: Trigger,
        workspace: Path | None = None,
        dry_run: bool = False,
        approvals: Iterable[str] = (),
        mandate: Mandate | None = None,
    ) -> RunRecord:
        """Run *agent_name* and return the record. Never raises for run outcomes."""
        p = self._p
        if agent_name not in p.agents:
            raise KeyError(f"unknown agent '{agent_name}' (known: {', '.join(sorted(p.agents))})")
        agent = p.agents[agent_name]
        resolved = mandate or p.mandates.resolve(agent_name, repository, environment)
        run_id = uuid.uuid4().hex
        if resolved is None:
            record = RunRecord(
                run_id=run_id,
                agent=agent_name,
                repository=repository,
                environment=environment,
                trigger=trigger,
                mandate=Mandate(agent=agent_name, kill_switch=True, source="none"),
                status=RunStatus.DENIED,
                error="no mandate applies to this agent, repository and environment",
                finished_at=datetime.now(UTC),
            )
            p.ledger.append(run_id, "run.denied", {"agent": agent_name, "reason": record.error})
            metrics.RUNS_TOTAL.labels(agent_name, record.status.value).inc()
            return record

        skills = p.skills.for_agent(agent_name, tuple(agent.default_skills) + resolved.skills)
        ctx = RunContext(
            run_id=run_id,
            agent=agent_name,
            repository=repository,
            environment=environment,
            trigger=trigger,
            mandate=resolved,
            gateway=p.gateway,
            tools=p.tools,
            prompts=p.prompts,
            skills=skills,
            ledger=p.ledger,
            workspace=workspace or Path.cwd(),
            dry_run=dry_run,
            approvals=approvals,
        )
        record = RunRecord(
            run_id=run_id,
            agent=agent_name,
            repository=repository,
            environment=environment,
            trigger=trigger,
            mandate=resolved,
        )
        p.ledger.append(
            run_id,
            "run.started",
            {
                "agent": agent_name,
                "repository": repository,
                "environment": environment,
                "trigger": trigger.model_dump(mode="json"),
                "mandate": {
                    "autonomy": resolved.autonomy.name,
                    "tier": resolved.model_tier,
                    "verification": resolved.verification,
                    "max_remote_class": resolved.max_remote_class.name,
                    "source": resolved.source,
                },
                "skills": [{"id": s.id, "sha256": s.sha256} for s in skills],
                "dry_run": dry_run,
            },
        )
        metrics.RUNS_IN_FLIGHT.labels(agent_name).inc()
        started = time.monotonic()
        try:
            with span("regent.run", agent=agent_name, repository=repository, run_id=run_id):
                self._execute(agent, ctx, record)
        except MandateDenied as exc:
            record.status = RunStatus.DENIED
            record.error = str(exc)
            record.pending_call = exc.call
        except ApprovalRequired as exc:
            record.status = RunStatus.AWAITING_APPROVAL
            record.error = str(exc)
            record.pending_call = exc.call
        except BudgetExceeded as exc:
            record.status = RunStatus.BUDGET_EXCEEDED
            record.error = str(exc)
        except (ProviderError, ConfidentialityViolation) as exc:
            record.status = RunStatus.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            log.error("run %s crashed: %s", run_id, traceback.format_exc())
            record.status = RunStatus.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
        finally:
            record.usage = ctx.usage
            record.finished_at = datetime.now(UTC)
            duration = time.monotonic() - started
            metrics.RUNS_IN_FLIGHT.labels(agent_name).dec()
            metrics.RUNS_TOTAL.labels(agent_name, record.status.value).inc()
            metrics.RUN_DURATION.labels(agent_name).observe(duration)
            p.ledger.append(
                run_id,
                "run.finished",
                {
                    "status": record.status.value,
                    "error": record.error,
                    "usage": record.usage.model_dump(),
                    "duration_s": round(duration, 2),
                    "pending_call": record.pending_call.model_dump()
                    if record.pending_call
                    else None,
                },
            )
        return record

    @staticmethod
    def _execute(agent: Agent, ctx: RunContext, record: RunRecord) -> None:
        # Phase 1 — analyse: only READ tools.
        ctx.set_phase_gate(RiskClass.READ)
        output = agent.analyse(ctx)
        ctx.record("analysis", {"output": output.as_dict()})

        # Phase 2 — verify.
        verdict = verify(agent, output, ctx)
        if not verdict.accepted and ctx.mandate.verification == "required":
            record.status = RunStatus.FAILED
            record.error = "verification rejected the output: " + "; ".join(verdict.issues[:5])
            record.output = {"analysis": output.as_dict(), "verdict": verdict.as_dict()}
            return

        # Phase 3 — act: the mandate's autonomy is the ceiling.
        ctx.set_phase_gate(RiskClass(min(int(ctx.mandate.autonomy), int(RiskClass.DESTRUCTIVE))))
        actions = agent.act(output, ctx)
        record.status = RunStatus.SUCCEEDED
        record.output = {
            "analysis": output.as_dict(),
            "verdict": verdict.as_dict(),
            "actions": actions,
        }
