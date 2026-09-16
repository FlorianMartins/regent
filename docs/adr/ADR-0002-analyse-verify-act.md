# ADR-0002 — Analyse → verify → act, with an independent critic

**Status:** Accepted (2026-09)

## Context

A model's output can be plausible and wrong; a model asked to check its own work tends to agree with itself. Actions must only follow outputs that survived a check the author did not control.

## Decision

Every run has three phases enforced by the runner: **analyse** (READ tools only; produce a structured output with evidence), **verify** (the agent's **deterministic checks** in code, then a **critic**: a second model call with a different prompt, `verifier@1`, on a tier never cheaper than the author's, told to reject and never fix), **act** (tools up to the mandate's autonomy). The mandate's `verification` field says whether a rejection stops the run (`required`), is logged (`advisory`), or the step is skipped (`none`). Verdicts are written to the ledger.

## Consequences

- Two model calls per run instead of one (cost +30–60 %); accepted for anything that leads to an action.
- Checks make the organisation's hard rules non-negotiable (a fix that does not scan clean is rejected whatever the critic says).
- Agents must expose `checks()` and `verification_focus()`; the test suite covers rejection paths.

## Alternatives considered

- **Self-critique in the same call** — same prompt, same biases.
- **Human review only** — does not scale to L3 use cases; humans still decide where the mandate says so.
- **Majority vote of several models** — cost and latency without the structural independence a different *prompt* and *deterministic* checks give.
