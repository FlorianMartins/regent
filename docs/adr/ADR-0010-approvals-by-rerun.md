# ADR-0010 — Approvals by re-run with pre-approved tools

**Status:** Accepted (2026-09)

## Context

Some tools need a human even inside the autonomy level (`requires_approval`). Suspending a process for hours needs a durable-execution engine. Phase 1 runs inside CI jobs, which cannot wait.

## Decision

A run that hits an approval-gated tool ends with status `awaiting_approval` and records the pending call (tool + arguments) in the record and the ledger. Approval = **re-running the agent with that tool pre-approved** (`--approve <glob>` in the CLI, `tools` in `POST /runs/{id}/approve`), recorded as an `approval` event with the approver. Agents are therefore **idempotent**: they re-read the world and their write tools are safe to attempt again (a review posted twice is a visible, harmless duplicate; a merge of a merged PR fails cleanly). In CI, the approval step sits behind a GitHub environment with required reviewers.

## Consequences

- No scheduler, no suspended state to persist; works identically in CI and in the control plane.
- The approved re-run costs another model pass (bounded by the budget).
- If the world changed between the two runs (new commits), the second run sees the new state — which is the correct behaviour.
- When runs must wait for days or resume mid-way with many steps, **Temporal** is the intended engine (phase 3); the `Runner` interface is where it plugs in.

## Alternatives considered

- **Suspend and resume in-process** — lost on restart; impossible in a CI job.
- **Temporal now** — operational weight not justified by six single-pass agents.
