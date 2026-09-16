"""The gateway itself: every LLM call passes here, in this order.

1. **Redaction** — credentials never reach a provider (`core.redaction`).
2. **Confidentiality** — content above the mandate's ``max_remote_class`` is
   refused for remote providers (`core.models.DataClass`).
3. **Routing** — the mandate's tier becomes a model; thin budgets degrade.
4. **Budget** — usage is charged and ceilings enforced.
5. **Audit** — prompt id, model, tokens, cost and redactions go to the ledger.
6. **Metrics** — counters and histograms for Prometheus.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from regent.core.budget import BudgetMeter
from regent.core.models import DataClass, Mandate
from regent.core.redaction import redact
from regent.gateway.models import Completion, CompletionRequest, Message
from regent.gateway.providers import Provider, ProviderError
from regent.gateway.router import Router
from regent.observability import metrics


class ConfidentialityViolation(PermissionError):
    """Content classified above what may leave the organisation was about to."""


class Gateway:
    """Bind a provider, a router and (per run) a mandate and a budget meter."""

    def __init__(
        self,
        provider: Provider,
        router: Router | None = None,
        local_provider: Provider | None = None,
    ) -> None:
        self._provider = provider
        self._local = local_provider
        self._router = router or Router()

    @property
    def provider(self) -> Provider:
        """The default provider."""
        return self._provider

    def _pick_provider(self, request: CompletionRequest, mandate: Mandate) -> Provider:
        if request.classification <= mandate.max_remote_class:
            return self._provider
        if self._provider.locality == "local":
            return self._provider
        if self._local is not None:
            return self._local
        raise ConfidentialityViolation(
            f"content is {request.classification.name} but the mandate only allows "
            f"{mandate.max_remote_class.name} to leave for a remote provider, "
            "and no local provider is configured"
        )

    def complete(
        self,
        request: CompletionRequest,
        *,
        mandate: Mandate,
        meter: BudgetMeter,
        audit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Completion:
        """Run one completion under *mandate*, charging *meter* and reporting to *audit*."""
        emit = audit or (lambda _kind, _data: None)
        meter.check_time()
        provider = self._pick_provider(request, mandate)

        system_red = redact(request.system)
        messages: list[Message] = []
        redactions: list[str] = list(system_red.findings)
        for message in request.messages:
            cleaned = redact(message.content)
            redactions.extend(cleaned.findings)
            messages.append(Message(role=message.role, content=cleaned.text))
        safe = request.model_copy(update={"system": system_red.text, "messages": tuple(messages)})

        for kind in redactions:
            metrics.REDACTIONS_TOTAL.labels(kind).inc()

        route = self._router.resolve(request.tier, meter.remaining_usd())
        try:
            completion = provider.complete(safe, route.model)
        except ProviderError as exc:
            emit(
                "llm.error",
                {"prompt_id": request.prompt_id, "model": route.model, "error": str(exc)},
            )
            raise
        meter.charge(completion.usage)
        emit(
            "llm.call",
            {
                "prompt_id": request.prompt_id,
                "provider": provider.name,
                "model": completion.model,
                "tier": route.tier,
                "degraded": route.degraded,
                "classification": request.classification.name,
                "redactions": sorted(set(redactions)),
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                "cache_read_tokens": completion.usage.cache_read_tokens,
                "usd": completion.usage.usd,
                "stop_reason": completion.stop_reason,
                "refused": completion.refused,
            },
        )
        return completion


def wrap_untrusted(label: str, content: str, classification: DataClass) -> str:
    """Mark data that came from outside the platform as data, not instructions.

    Diffs, logs, tickets and alert payloads are attacker-controllable. The LLM
    Security Lab showed that concatenating them into instructions is how prompt
    injection lands (OWASP LLM01/LLM08); the fix is a channel the system prompt
    can name and the model is told to treat as inert.
    """
    safe = content.replace("</untrusted_data>", "</untrusted_data​>")
    return (
        f'<untrusted_data label="{label}" classification="{classification.name}">\n'
        f"{safe}\n</untrusted_data>"
    )
