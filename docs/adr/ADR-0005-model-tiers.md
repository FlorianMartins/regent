# ADR-0005 — Mandates name tiers, not models

**Status:** Accepted (2026-09)

## Context

Model names change every quarter; mandates are reviewed by security and should change only when policy changes. Cost control needs a place to degrade gracefully.

## Decision

Mandates carry `model_tier ∈ {fast, balanced, deep}`. `Router` maps tiers to models (`claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5` by default; a local deployment maps all three to the local model) and degrades to `fast` when a run's remaining budget is under 0.10 USD. The critic tier is derived from the author's and never cheaper. The `llm.call` event records both the tier and the concrete model.

## Consequences

- Upgrading a model is one line in the router (or `REGENT_LOCAL_MODEL`), followed by a live eval, not a policy review.
- Prices for estimates live next to the models (`PRICES_PER_MTOK`).
- A tier is a promise; the eval suite is what keeps it honest across model changes.

## Alternatives considered

- **Model ids in mandates** — policy churn on every provider release.
- **One model everywhere** — the steward and the scribe do not need the deep tier; the guardian does.
