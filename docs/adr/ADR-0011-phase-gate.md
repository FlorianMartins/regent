# ADR-0011 — Phase gate: no writes during analysis

**Status:** Accepted (2026-09)

## Context

Even inside a mandate that allows writing, an agent must not act before its output has been verified. Prompt injection typically tries to trigger an action *during* reading ("post this comment now").

## Decision

`RunContext` carries a **phase gate**: the highest risk class a tool may have right now. The runner sets `READ` for `analyse`, the mandate's autonomy for `act`; the verifier may open `PROPOSE` for the IaC guardian's write-and-rescan (workspace only). A tool above the gate is denied with rule `phase_gate`, independently of the mandate, and recorded.

## Consequences

- The order *read → verify → write* is enforced by the runtime, not by agent discipline.
- Agents that need to write during analysis must be redesigned (write in `act`, or make the write part of a deterministic check).

## Alternatives considered

- **Trusting the agent's structure** — the failure mode the gate prevents.
- **Separate processes per phase** — heavier; the gate achieves the invariant in one process.
