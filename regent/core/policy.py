"""Mandate resolution and tool-call authorisation.

Two questions, answered in order:

1. *Which mandate applies?* — :class:`MandateStore` loads YAML documents and
   picks the most specific one for ``(agent, repository, environment)``.
2. *May this call proceed?* — :func:`evaluate` compares a tool call with the
   mandate and answers ``allow``, ``deny`` or ``require_approval``, always with
   the rule that fired, so the ledger can explain every decision.

The engine is deliberately in-process and dependency-free: it must be unit
testable, run inside a CI job with no network, and be readable by an auditor.
Cluster-level admission (what may be *deployed*) is a different question and
lives in ``policies/rego`` for OPA / Conftest.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from regent.core.models import (
    Autonomy,
    Budget,
    DataClass,
    Decision,
    DecisionKind,
    Mandate,
    RiskClass,
)


class PolicyError(ValueError):
    """A mandate file is malformed or contradicts itself."""


def _matches(patterns: Iterable[str], value: str) -> str | None:
    """Return the first glob pattern matching *value*, or ``None``."""
    for pattern in patterns:
        if fnmatch.fnmatchcase(value, pattern):
            return pattern
    return None


class MandateStore:
    """Loads mandates from YAML and resolves the one that applies to a run."""

    def __init__(self, mandates: Iterable[Mandate] = ()) -> None:
        self._mandates: list[Mandate] = list(mandates)

    # ---- loading ----------------------------------------------------------

    @classmethod
    def from_directory(cls, directory: Path) -> MandateStore:
        """Load every ``*.yaml`` / ``*.yml`` file in *directory*."""
        store = cls()
        for path in sorted(directory.glob("*.y*ml")):
            store.load_file(path)
        return store

    def load_file(self, path: Path) -> None:
        """Load one YAML document (a mapping or a list of mappings)."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PolicyError(f"{path}: invalid YAML: {exc}") from exc
        documents = raw if isinstance(raw, list) else [raw]
        for doc in documents:
            if not isinstance(doc, dict):
                raise PolicyError(f"{path}: expected a mapping, got {type(doc).__name__}")
            self._mandates.append(self._parse(doc, source=str(path)))

    @staticmethod
    def _parse(doc: dict[str, Any], *, source: str) -> Mandate:
        try:
            autonomy = doc.get("autonomy", "L1_ADVISE")
            data: dict[str, Any] = {
                "agent": doc["agent"],
                "autonomy": Autonomy[autonomy] if isinstance(autonomy, str) else Autonomy(autonomy),
                "allowed_tools": tuple(doc.get("allowed_tools", ())),
                "denied_tools": tuple(doc.get("denied_tools", ())),
                "requires_approval": tuple(doc.get("requires_approval", ())),
                "budget": Budget(**doc.get("budget", {})),
                "model_tier": doc.get("model_tier", "balanced"),
                "scopes": tuple(doc.get("scopes", ("*",))),
                "environments": tuple(doc.get("environments", ("*",))),
                "max_remote_class": DataClass[doc.get("max_remote_class", "INTERNAL")],
                "verification": doc.get("verification", "required"),
                "skills": tuple(doc.get("skills", ())),
                "kill_switch": bool(doc.get("kill_switch", False)),
                "source": source,
            }
        except KeyError as exc:
            raise PolicyError(f"{source}: missing key {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise PolicyError(f"{source}: {exc}") from exc
        return Mandate(**data)

    # ---- resolution -------------------------------------------------------

    def add(self, mandate: Mandate) -> None:
        """Register a mandate programmatically (tests, API)."""
        self._mandates.append(mandate)

    def all(self) -> list[Mandate]:
        """Every loaded mandate, in load order."""
        return list(self._mandates)

    def resolve(self, agent: str, repository: str, environment: str) -> Mandate | None:
        """Pick the most specific mandate for the triple, or ``None`` if none applies.

        Specificity is the number of non-wildcard scope and environment patterns;
        ties go to the last loaded document, so a repository-local file overrides
        the organisation defaults. A kill switch on *any* matching mandate wins.
        """
        candidates: list[tuple[int, int, Mandate]] = []
        for index, mandate in enumerate(self._mandates):
            if mandate.agent != agent:
                continue
            if _matches(mandate.scopes, repository) is None:
                continue
            if _matches(mandate.environments, environment) is None:
                continue
            specificity = sum(1 for p in (*mandate.scopes, *mandate.environments) if p != "*")
            candidates.append((specificity, index, mandate))
        if not candidates:
            return None
        if any(m.kill_switch for _, _, m in candidates):
            chosen = max(candidates, key=lambda c: (c[0], c[1]))[2]
            return chosen.model_copy(update={"kill_switch": True})
        return max(candidates, key=lambda c: (c[0], c[1]))[2]


def evaluate(mandate: Mandate, tool_name: str, risk: RiskClass) -> Decision:
    """Decide whether *tool_name* (of class *risk*) may run under *mandate*.

    Rules, in order — the first that fires wins:

    1. ``kill_switch`` denies everything.
    2. A matching ``denied_tools`` pattern denies.
    3. A tool that is not in ``allowed_tools`` is denied (allow-list, never deny-list).
    4. ``DESTRUCTIVE`` tools are denied unless the mandate is ``L4_ACT`` — and no
       shipped mandate is.
    5. A tool whose risk class exceeds the autonomy level is denied.
    6. A matching ``requires_approval`` pattern asks for a human.
    7. Otherwise the call is allowed.
    """
    if mandate.kill_switch:
        return Decision(
            kind=DecisionKind.DENY, reason="agent disabled by kill switch", rule="kill_switch"
        )
    if (pattern := _matches(mandate.denied_tools, tool_name)) is not None:
        return Decision(
            kind=DecisionKind.DENY, reason=f"tool matches denied pattern '{pattern}'", rule="denied"
        )
    if _matches(mandate.allowed_tools, tool_name) is None:
        return Decision(
            kind=DecisionKind.DENY,
            reason="tool is not in the mandate allow-list",
            rule="not_allowed",
        )
    if risk is RiskClass.DESTRUCTIVE and mandate.autonomy < Autonomy.L4_ACT:
        return Decision(
            kind=DecisionKind.DENY,
            reason="destructive tools need L4_ACT, which no mandate grants",
            rule="destructive",
        )
    if risk.minimum_autonomy > mandate.autonomy:
        return Decision(
            kind=DecisionKind.DENY,
            reason=(
                f"tool risk {risk.name} needs {risk.minimum_autonomy.name}, "
                f"mandate grants {mandate.autonomy.name}"
            ),
            rule="autonomy",
        )
    if (pattern := _matches(mandate.requires_approval, tool_name)) is not None:
        return Decision(
            kind=DecisionKind.REQUIRE_APPROVAL,
            reason=f"tool matches approval pattern '{pattern}'",
            rule="approval",
        )
    return Decision(kind=DecisionKind.ALLOW, reason="within mandate", rule="allow")
