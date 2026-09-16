"""LLM providers behind one protocol.

* :class:`AnthropicProvider` — the production default (Claude via the official SDK).
* :class:`OpenAICompatibleProvider` — any OpenAI-style endpoint, used for
  *local* models (vLLM, Ollama, TGI) when data must not leave the network.
* :class:`ReplayProvider` — deterministic fixtures for tests, evals and CI.
  Nothing in the test suite needs a key or the network.

Adding a provider means implementing :class:`Provider`; nothing else changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from regent.core.models import Usage
from regent.gateway.models import Completion, CompletionRequest


class ProviderError(RuntimeError):
    """The provider could not produce a completion."""


@runtime_checkable
class Provider(Protocol):
    """What the gateway needs from a model backend."""

    name: str
    locality: str
    """``remote`` when data leaves the organisation, ``local`` otherwise."""

    def complete(self, request: CompletionRequest, model: str) -> Completion:
        """Produce a completion with *model*."""
        ...


# ---------------------------------------------------------------------------
# Pricing (USD per million tokens). Kept here so FinOps has one place to update.
# ---------------------------------------------------------------------------
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    """Cost of one call; cached input is billed at a tenth of the input price."""
    price_in, price_out = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    uncached = max(0, input_tokens - cache_read)
    usd = (uncached * price_in + cache_read * price_in * 0.1 + output_tokens * price_out) / 1e6
    return round(usd, 6)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object in *text*; tolerate code fences."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
class AnthropicProvider:
    """Claude through the official SDK.

    * Adaptive thinking is on, with ``effort`` mapped from the request.
    * The system prompt is marked cacheable: agents keep it stable so repeated
      runs pay a tenth of the price for it.
    * Structured output uses ``output_config.format`` so the answer is valid
      JSON by construction, not by luck.
    """

    name = "anthropic"
    locality = "remote"

    def __init__(self, api_key: str | None = None, timeout_s: float = 300.0) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=3)

    def complete(self, request: CompletionRequest, model: str) -> Completion:
        """Call the Messages API once and normalise the answer."""
        import anthropic

        system: list[dict[str, Any]] = [{"type": "text", "text": request.system}]
        if request.cache_system:
            system[0]["cache_control"] = {"type": "ephemeral"}
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_output_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": request.effort},
        }
        if request.output_schema is not None:
            params["output_config"]["format"] = {
                "type": "json_schema",
                "schema": request.output_schema,
            }
        try:
            response = self._client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise ProviderError(f"rate limited: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"api error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"connection error: {exc}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return Completion(
            text=text,
            parsed=_extract_json(text) if request.output_schema else None,
            model=response.model,
            provider=self.name,
            stop_reason=str(response.stop_reason),
            refused=response.stop_reason == "refusal",
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                usd=estimate_usd(model, usage.input_tokens, usage.output_tokens, cache_read),
                llm_calls=1,
            ),
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible (local models)
# ---------------------------------------------------------------------------
class OpenAICompatibleProvider:
    """A ``/v1/chat/completions`` endpoint (vLLM, Ollama, TGI, LiteLLM).

    Declared ``local`` because that is what it is for: keeping RESTRICTED data
    inside the network. Point it at a SaaS and the classification guard is
    only as honest as your configuration.
    """

    name = "openai-compatible"
    locality = "local"

    def __init__(self, base_url: str, api_key: str = "", timeout_s: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s

    def complete(self, request: CompletionRequest, model: str) -> Completion:
        """POST one chat completion."""
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                *({"role": m.role, "content": m.content} for m in request.messages),
            ],
        }
        if request.output_schema is not None:
            body["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._base_url}/chat/completions", json=body, headers=self._headers
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"local provider failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("local provider returned an unexpected shape") from exc
        usage = data.get("usage", {})
        return Completion(
            text=text,
            parsed=_extract_json(text) if request.output_schema else None,
            model=model,
            provider=self.name,
            stop_reason=str(data["choices"][0].get("finish_reason", "stop")),
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                usd=0.0,
                llm_calls=1,
            ),
        )


# ---------------------------------------------------------------------------
# Replay (fixtures)
# ---------------------------------------------------------------------------
def request_fingerprint(request: CompletionRequest) -> str:
    """Stable identifier of a request, for recording and replaying."""
    canonical = json.dumps(
        {
            "prompt_id": request.prompt_id,
            "messages": [m.model_dump() for m in request.messages],
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ReplayProvider:
    """Answers from fixtures. Deterministic, offline, free.

    Fixtures are matched in order: by exact fingerprint, then by ``prompt_id``
    (first unused answer for that prompt), so a test can script a whole run.
    An unmatched request raises — silence would hide a broken test.
    """

    name = "replay"
    locality = "local"

    def __init__(
        self,
        by_fingerprint: dict[str, dict[str, Any]] | None = None,
        by_prompt: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._by_fingerprint = dict(by_fingerprint or {})
        self._by_prompt = {k: list(v) for k, v in (by_prompt or {}).items()}
        self.requests: list[CompletionRequest] = []

    @classmethod
    def from_file(cls, path: Path) -> ReplayProvider:
        """Load a JSON fixture ``{"by_fingerprint": {...}, "by_prompt": {...}}``."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(raw.get("by_fingerprint"), raw.get("by_prompt"))

    def complete(self, request: CompletionRequest, model: str) -> Completion:
        """Return the scripted answer for *request*."""
        self.requests.append(request)
        answer = self._by_fingerprint.get(request_fingerprint(request))
        if answer is None:
            queue = self._by_prompt.get(request.prompt_id)
            if queue:
                answer = queue.pop(0)
        if answer is None:
            raise ProviderError(
                f"no replay fixture for prompt '{request.prompt_id}' "
                f"(fingerprint {request_fingerprint(request)})"
            )
        text = answer["text"] if "text" in answer else json.dumps(answer["json"])
        parsed = answer.get("json") if request.output_schema else None
        if parsed is None and request.output_schema:
            parsed = _extract_json(text)
        return Completion(
            text=text,
            parsed=parsed,
            model=model,
            provider=self.name,
            usage=Usage(
                input_tokens=int(answer.get("input_tokens", 1000)),
                output_tokens=int(answer.get("output_tokens", 200)),
                usd=float(answer.get("usd", 0.0)),
                llm_calls=1,
            ),
        )
