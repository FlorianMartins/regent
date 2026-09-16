"""What every agent is: a bounded automation with three phases.

1. **Analyse** — read (through READ tools), reason (through the gateway), and
   produce a *structured* output. No side effects.
2. **Verify** — deterministic checks the agent declares, then an independent
   LLM critic. A rejected output never reaches phase 3.
3. **Act** — do something with the output, through tools the mandate allows.

Agents do not choose their model, their budget or their permissions. They
declare what they need; the mandate decides what they get.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from regent.core.models import RiskClass

if TYPE_CHECKING:
    from regent.runtime.context import RunContext


class CheckResult(BaseModel):
    """Outcome of one deterministic check."""

    model_config = ConfigDict(frozen=True)

    check: str
    passed: bool
    detail: str = ""


class AgentOutput(BaseModel):
    """Every agent returns a subclass of this. ``summary`` is what humans read."""

    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    """Facts the output rests on — quoted lines, tool results, rule ids."""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view."""
        return self.model_dump(mode="json")


class Agent(ABC):
    """Base class. Subclasses set the class attributes and implement the phases."""

    name: ClassVar[str]
    description: ClassVar[str]
    default_tier: ClassVar[str] = "balanced"
    default_skills: ClassVar[tuple[str, ...]] = ()
    highest_risk: ClassVar[RiskClass] = RiskClass.ADVISE
    """The riskiest tool the agent will ever ask for. Documentation and a sanity check."""
    output_type: ClassVar[type[AgentOutput]] = AgentOutput

    @abstractmethod
    def analyse(self, ctx: RunContext) -> AgentOutput:
        """Phase 1: read and reason. Must not call tools above READ."""

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:  # noqa: ARG002
        """Phase 2a: deterministic checks on the output. Default: none."""
        return []

    def verification_focus(self) -> str:
        """What the critic should look for. Agents override with domain specifics."""
        return "unsupported claims, missing evidence, actions that exceed the stated intent"

    @abstractmethod
    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        """Phase 3: do something with a verified output. Returns what was done."""

    def output_schema(self) -> dict[str, Any]:
        """JSON schema of the structured output, for the gateway."""
        schema = self.output_type.model_json_schema()
        schema.pop("title", None)
        return _strict(schema)


T = TypeVar("T", bound=AgentOutput)


def expect(output: AgentOutput, kind: type[T]) -> T:
    """Narrow an output to the agent's own type; a mismatch is a programming error."""
    if not isinstance(output, kind):
        raise TypeError(f"expected {kind.__name__}, got {type(output).__name__}")
    return output


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic schema acceptable for strict structured output."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        schema["required"] = list(props)
        for value in props.values():
            _strict(value)
    if "items" in schema and isinstance(schema["items"], dict):
        _strict(schema["items"])
    for key in ("$defs", "definitions"):
        for value in schema.get(key, {}).values():
            _strict(value)
    for key in ("anyOf", "oneOf", "allOf"):
        for value in schema.get(key, []):
            _strict(value)
    schema.pop("default", None)
    return schema
