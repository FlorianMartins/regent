"""The run context: what an agent can do, and the guard rails around it."""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from regent.core.budget import BudgetMeter
from regent.core.ledger import Ledger
from regent.core.models import (
    DataClass,
    DecisionKind,
    Mandate,
    RiskClass,
    ToolCall,
    ToolResult,
    Trigger,
    Usage,
)
from regent.core.policy import evaluate
from regent.core.redaction import redact
from regent.gateway.gateway import Gateway, wrap_untrusted
from regent.gateway.models import Completion, CompletionRequest, Message
from regent.gateway.prompts import PromptRegistry
from regent.observability import metrics
from regent.observability.tracing import span
from regent.skills import Skill, SkillRegistry
from regent.tools.base import ToolContext, ToolRegistry

log = logging.getLogger("regent.runtime")


class MandateDenied(PermissionError):
    """The agent asked for something its mandate does not cover."""

    def __init__(self, call: ToolCall, reason: str, rule: str) -> None:
        self.call = call
        self.reason = reason
        self.rule = rule
        super().__init__(f"{call.tool}: {reason} (rule: {rule})")


class ApprovalRequired(RuntimeError):
    """A human must approve this call before the run can continue."""

    def __init__(self, call: ToolCall, reason: str) -> None:
        self.call = call
        self.reason = reason
        super().__init__(f"{call.tool} needs approval: {reason}")


class RunContext:
    """Everything one agent run may touch, mediated."""

    def __init__(
        self,
        *,
        run_id: str,
        agent: str,
        repository: str,
        environment: str,
        trigger: Trigger,
        mandate: Mandate,
        gateway: Gateway,
        tools: ToolRegistry,
        prompts: PromptRegistry,
        skills: list[Skill],
        ledger: Ledger,
        workspace: Path,
        dry_run: bool = False,
        approvals: Iterable[str] = (),
        phase_gate: RiskClass = RiskClass.READ,
    ) -> None:
        self.run_id = run_id
        self.agent = agent
        self.repository = repository
        self.environment = environment
        self.trigger = trigger
        self.mandate = mandate
        self.workspace = workspace
        self.dry_run = dry_run
        self.skills = skills
        self._gateway = gateway
        self._tools = tools
        self._prompts = prompts
        self._ledger = ledger
        self._meter = BudgetMeter(mandate.budget)
        self._approvals = tuple(approvals)
        self._phase_gate = phase_gate
        self.tool_results: list[ToolResult] = []
        self.completions: list[Completion] = []
        self.highest_classification = DataClass.PUBLIC

    # ---- accounting -------------------------------------------------------

    @property
    def usage(self) -> Usage:
        """Spend so far."""
        return self._meter.usage

    @property
    def meter(self) -> BudgetMeter:
        """The budget meter (read-only use recommended)."""
        return self._meter

    def set_phase_gate(self, risk: RiskClass) -> None:
        """Highest risk class tools may have in the current phase."""
        self._phase_gate = risk

    def record(self, kind: str, data: dict[str, Any] | None = None) -> None:
        """Write a custom event to the ledger."""
        self._ledger.append(self.run_id, kind, data)

    # ---- reasoning --------------------------------------------------------

    def llm(
        self,
        prompt: str,
        *,
        values: dict[str, str] | None = None,
        user: str,
        schema: dict[str, Any] | None = None,
        classification: DataClass | None = None,
        tier: str | None = None,
        effort: str = "medium",
        max_output_tokens: int = 8_000,
    ) -> Completion:
        """Render a versioned prompt and call the gateway.

        The system prompt is the template plus the skills in force; ``user`` is
        the request of this call. Untrusted data must be wrapped with
        :meth:`untrusted` by the caller so the model can tell data from orders.
        """
        template = self._prompts.get(prompt)
        system = template.render(**(values or {}))
        composed = SkillRegistry.compose(self.skills)
        if composed:
            system = f"{system}\n\n{composed}"
        request = CompletionRequest(
            system=system,
            messages=(Message(role="user", content=user),),
            output_schema=schema,
            tier=tier or self.mandate.model_tier,
            effort=effort,
            classification=classification or self.highest_classification,
            prompt_id=template.id,
            max_output_tokens=max_output_tokens,
        )
        with span("regent.llm", agent=self.agent, prompt_id=template.id, tier=request.tier) as s:
            completion = self._gateway.complete(
                request, mandate=self.mandate, meter=self._meter, audit=self.record
            )
            s.set_attribute("model", completion.model)
            s.set_attribute("usd", completion.usage.usd)
        metrics.LLM_CALLS_TOTAL.labels(self.agent, completion.provider, completion.model).inc()
        metrics.LLM_TOKENS_TOTAL.labels(self.agent, completion.model, "input").inc(
            completion.usage.input_tokens
        )
        metrics.LLM_TOKENS_TOTAL.labels(self.agent, completion.model, "output").inc(
            completion.usage.output_tokens
        )
        metrics.LLM_USD_TOTAL.labels(self.agent, completion.model).inc(completion.usage.usd)
        self.completions.append(completion)
        if completion.refused:
            self.record("llm.refused", {"prompt_id": template.id, "model": completion.model})
        return completion

    def untrusted(self, label: str, content: str, classification: DataClass | None = None) -> str:
        """Wrap external content and raise the run's classification accordingly."""
        level = classification or DataClass.INTERNAL
        if level > self.highest_classification:
            self.highest_classification = level
        return wrap_untrusted(label, content, level)

    # ---- acting -----------------------------------------------------------

    def _pre_approved(self, call: ToolCall) -> bool:
        return any(fnmatch.fnmatchcase(call.tool, pattern) for pattern in self._approvals)

    def tool(self, name: str, /, **arguments: Any) -> ToolResult:
        """Call a tool: policy first, then execution, then audit. Always in that order."""
        call = ToolCall(tool=name, arguments=arguments)
        self._meter.check_time()
        if name not in self._tools:
            raise MandateDenied(call, "tool does not exist", "unknown_tool")
        tool = self._tools.get(name)
        risk = tool.spec.risk

        decision = evaluate(self.mandate, name, risk)
        if decision.kind is DecisionKind.ALLOW and risk > self._phase_gate:
            decision = decision.model_copy(
                update={
                    "kind": DecisionKind.DENY,
                    "reason": (
                        f"tool risk {risk.name} is above the current phase gate "
                        f"{self._phase_gate.name} (analyse before you act)"
                    ),
                    "rule": "phase_gate",
                }
            )
        if decision.kind is DecisionKind.REQUIRE_APPROVAL and self._pre_approved(call):
            decision = decision.model_copy(
                update={
                    "kind": DecisionKind.ALLOW,
                    "reason": "approved by a human",
                    "rule": "approved",
                }
            )
        self._ledger.append(
            self.run_id,
            "tool.decision",
            {
                "call_id": call.call_id,
                "tool": name,
                "risk": risk.name,
                "decision": decision.kind.value,
                "rule": decision.rule,
                "reason": decision.reason,
                "arguments": _summarise(arguments),
            },
        )
        metrics.TOOL_CALLS_TOTAL.labels(self.agent, name, decision.kind.value).inc()
        if decision.kind is DecisionKind.DENY:
            raise MandateDenied(call, decision.reason, decision.rule)
        if decision.kind is DecisionKind.REQUIRE_APPROVAL:
            raise ApprovalRequired(call, decision.reason)

        with span("regent.tool", agent=self.agent, tool=name, risk=risk.name):
            result = tool.run(arguments, self._tool_context())
        result = result.model_copy(update={"call_id": call.call_id})
        self._meter.charge(Usage(tool_calls=1))
        if result.classification > self.highest_classification:
            self.highest_classification = result.classification
        self.tool_results.append(result)
        self._ledger.append(
            self.run_id,
            "tool.call",
            {
                "call_id": call.call_id,
                "tool": name,
                "ok": result.ok,
                "error": result.error,
                "classification": result.classification.name,
                "output": _summarise(result.output),
            },
        )
        return result

    def _tool_context(self) -> ToolContext:
        return ToolContext(
            run_id=self.run_id,
            repository=self.repository,
            workspace=self.workspace,
            dry_run=self.dry_run,
        )


def _summarise(value: Any, limit: int = 400) -> Any:
    """Bounded, redacted view of a value for the ledger."""
    if value is None:
        return None
    text = value if isinstance(value, str) else repr(value)
    cleaned = redact(text).text
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + f"… (+{len(cleaned) - limit})"
