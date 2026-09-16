# ADR-0016 — Offline replay evals in CI, live evals nightly

**Status:** Accepted (2026-09)

## Context

Prompts, skills, mandates and agents all change behaviour. Tests that need an API key and the network are flaky, slow, cost money on every push, and cannot run on forks. But a model update can only be caught against the real model.

## Decision

Eval cases are YAML (`evals/cases/`): a fake world (GitHub answers, tool stubs), **scripted model answers keyed by prompt id** (`ReplayProvider`), and assertions on the record and the GitHub writes. `regent evals` runs them **offline in CI on every change** and as a pytest. `regent evals --live` ignores the scripts and uses the configured provider; it runs **nightly** with a budget and the same assertions. A prompt or skill change must add or update a case.

## Consequences

- The pipeline needs no secret to prove the guard rails; forks and PRs from outside run the same checks.
- Offline cases test the *pipeline* (what is wrapped, denied, posted); live cases test the *model*; both are needed and the docs say which is which.
- The replay provider fails loudly on a missing fixture (`ProviderError`) so a broken case cannot pass silently.

## Alternatives considered

- **Live tests on every push** — cost, flakiness, secrets in PR builds.
- **Mocking the SDK ad hoc in each test** — no reusable cases, no live mode.
- **An external eval platform** — dependency and a second source of truth; may be added for dashboards, not for gating.
