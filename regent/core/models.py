"""Domain models shared by every part of the platform.

The vocabulary is deliberately small:

* An **agent** is a bounded automation (review a pull request, triage a failed
  build, …). It reasons with an LLM and acts through **tools**.
* A **mandate** is the contract under which an agent runs: how autonomous it
  may be, which tools it may call, how much it may spend, and which actions
  need a human. Nothing runs without a mandate.
* A **run** is one execution of one agent under one mandate. Every run leaves a
  tamper-evident trail in the ledger.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Autonomy(enum.IntEnum):
    """How far an agent may go without a human.

    The levels are ordered: a mandate at ``L2_PROPOSE`` implies everything a
    lower level allows. Tools declare the minimum level they need through their
    risk class, and the policy engine compares the two.
    """

    L0_OBSERVE = 0
    """Read and summarise. Produces a report, changes nothing."""

    L1_ADVISE = 1
    """Read and recommend where humans work (PR comment, ticket, chat)."""

    L2_PROPOSE = 2
    """Prepare a reversible change for a human to accept (open a PR, draft a plan)."""

    L3_ACT_REVERSIBLE = 3
    """Execute a reversible change on its own (re-run a job, merge a patch bump, roll back)."""

    L4_ACT = 4
    """Execute irreversible changes. Reserved; no shipped mandate grants it."""


class RiskClass(enum.IntEnum):
    """What a tool can do to the world. Maps to the minimum autonomy it needs."""

    READ = 0
    """Reads data. Never changes state."""

    ADVISE = 1
    """Writes where humans read: comments, tickets, notifications."""

    PROPOSE = 2
    """Creates a change humans still have to accept: branches, pull requests."""

    ACT_REVERSIBLE = 3
    """Changes state in a way that can be undone: re-run, merge with revert path, scale."""

    DESTRUCTIVE = 4
    """Cannot be undone: delete, force-push, drop, terminate."""

    @property
    def minimum_autonomy(self) -> Autonomy:
        """The autonomy level a mandate must grant for this class of tool."""
        return Autonomy(int(self))


class DataClass(enum.IntEnum):
    """Confidentiality of a piece of data, ordered from least to most sensitive.

    Every tool result carries a classification. The gateway refuses to send
    content classified above the mandate's ``max_remote_class`` to a provider
    that runs outside the organisation — a confidential diff can still be
    reasoned about, but only by a local model.
    """

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
    """Regulated or secret material (credentials, personal data, legal hold)."""


class Budget(BaseModel):
    """Hard ceilings for one run. Exceeding any of them stops the run."""

    model_config = ConfigDict(frozen=True)

    max_llm_calls: int = Field(default=20, ge=1)
    max_tool_calls: int = Field(default=50, ge=1)
    max_input_tokens: int = Field(default=400_000, ge=1)
    max_output_tokens: int = Field(default=60_000, ge=1)
    max_usd: float = Field(default=2.0, gt=0)
    max_duration_s: int = Field(default=900, ge=1)


class Mandate(BaseModel):
    """The contract under which an agent runs.

    Mandates live in ``policies/mandates/*.yaml`` and are resolved per
    (agent, repository, environment). They are the *only* way to widen what an
    agent can do — code changes cannot.
    """

    model_config = ConfigDict(frozen=True)

    agent: str
    autonomy: Autonomy = Autonomy.L1_ADVISE
    allowed_tools: tuple[str, ...] = ()
    """Glob patterns of tool names (``github.*``, ``cloudguard.scan``)."""
    denied_tools: tuple[str, ...] = ()
    """Glob patterns that win over ``allowed_tools``."""
    requires_approval: tuple[str, ...] = ()
    """Glob patterns of tools that need a human even inside the autonomy level."""
    budget: Budget = Field(default_factory=Budget)
    model_tier: str = "balanced"
    """``fast`` | ``balanced`` | ``deep`` — resolved by the gateway router."""
    scopes: tuple[str, ...] = ("*",)
    """Repositories or targets the mandate applies to (glob)."""
    environments: tuple[str, ...] = ("*",)
    """Deployment environments the mandate applies to (``dev``, ``prod`` …)."""
    max_remote_class: DataClass = DataClass.INTERNAL
    """Highest classification that may leave the organisation for a remote LLM."""
    verification: str = "required"
    """``required`` — a verifier must accept the output before any PROPOSE/ACT tool runs;
    ``advisory`` — verifier findings are logged only; ``none`` — no verifier."""
    skills: tuple[str, ...] = ()
    """Skills the agent must load on top of its own defaults."""
    kill_switch: bool = False
    """When true the agent is disabled everywhere, whatever else is granted."""
    source: str = "default"
    """Where the mandate came from, for the ledger."""

    def describe(self) -> dict[str, Any]:
        """Human-readable view: enum names instead of numbers."""
        data = self.model_dump(mode="json")
        data["autonomy"] = self.autonomy.name
        data["max_remote_class"] = self.max_remote_class.name
        return data


class DecisionKind(enum.StrEnum):
    """Outcome of a policy check."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class Decision(BaseModel):
    """Result of evaluating one tool call against a mandate."""

    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    reason: str
    rule: str
    """Identifier of the rule that fired, for the audit trail."""

    @property
    def allowed(self) -> bool:
        """True when the call may proceed right now."""
        return self.kind is DecisionKind.ALLOW


class ToolCall(BaseModel):
    """A request from an agent to run a tool."""

    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])


class ToolResult(BaseModel):
    """What a tool returned. ``ok=False`` is a normal outcome, not an exception."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    tool: str
    ok: bool
    output: Any = None
    error: str | None = None
    classification: DataClass = DataClass.INTERNAL


class Usage(BaseModel):
    """Token and money accounting for one or more LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0

    def add(self, other: Usage) -> Usage:
        """Return the sum of two usages (immutability keeps the ledger honest)."""
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            usd=round(self.usd + other.usd, 6),
            llm_calls=self.llm_calls + other.llm_calls,
            tool_calls=self.tool_calls + other.tool_calls,
        )


class RunStatus(enum.StrEnum):
    """Lifecycle of a run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    """The mandate refused something the agent needed. Nothing was changed."""
    AWAITING_APPROVAL = "awaiting_approval"
    """Paused on a tool that needs a human. Resumable."""
    BUDGET_EXCEEDED = "budget_exceeded"


class Trigger(BaseModel):
    """Why a run started — the event and its provenance."""

    model_config = ConfigDict(frozen=True)

    source: str
    """``cli`` | ``github`` | ``alertmanager`` | ``schedule`` | ``api``."""
    event: str
    """``pull_request.opened``, ``workflow_run.failed``, ``alert.firing`` …"""
    actor: str = "unknown"
    """Who or what caused the event (login, service account, webhook)."""
    payload: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    """Persistent summary of a run, as stored by the API and the CLI."""

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent: str
    repository: str
    environment: str = "dev"
    trigger: Trigger
    mandate: Mandate
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    usage: Usage = Field(default_factory=Usage)
    output: dict[str, Any] | None = None
    pending_call: ToolCall | None = None
    error: str | None = None
