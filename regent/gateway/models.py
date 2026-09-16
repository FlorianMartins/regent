"""Request and response shapes of the gateway. Provider-neutral by design."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from regent.core.models import DataClass, Usage


class Message(BaseModel):
    """One conversation turn. Content is plain text: agents do not send images."""

    model_config = ConfigDict(frozen=True)

    role: str
    """``user`` or ``assistant``."""
    content: str


class CompletionRequest(BaseModel):
    """What an agent asks for. The gateway fills in the model."""

    model_config = ConfigDict(frozen=True)

    system: str
    messages: tuple[Message, ...]
    output_schema: dict[str, Any] | None = None
    """JSON schema the answer must satisfy (structured output)."""
    max_output_tokens: int = 8_000
    tier: str = "balanced"
    effort: str = "medium"
    """``low`` | ``medium`` | ``high`` — depth of reasoning where the model supports it."""
    classification: DataClass = DataClass.INTERNAL
    """Highest classification of anything in ``system`` or ``messages``."""
    prompt_id: str = "adhoc"
    """Identifier and version of the prompt template, for the ledger."""
    cache_system: bool = True
    """Ask the provider to cache the (stable) system prompt across calls."""


class Completion(BaseModel):
    """What comes back. ``parsed`` is filled when ``output_schema`` was given."""

    model_config = ConfigDict(frozen=True)

    text: str
    parsed: dict[str, Any] | None = None
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str = "end_turn"
    refused: bool = False
    """The provider declined to answer (safety classifier). Treat as a failed call."""
