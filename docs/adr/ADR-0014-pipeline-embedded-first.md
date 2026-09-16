# ADR-0014 — Pipeline-embedded topology first, control plane second

**Status:** Accepted (2026-09)

## Context

A long-running control plane needs a webhook endpoint, an identity, secrets, scaling and on-call before the first agent delivers value. Most triggers (PR opened, build failed, release created) already run CI jobs with an identity and a checkout.

## Decision

Phase 1 runs agents as `regent run …` **inside CI jobs**: the job token is the identity (scoped by `permissions:`), the checkout is the workspace, the ledger is uploaded as an artefact, approvals use GitHub environments. Phase 2 adds the FastAPI **control plane** (`regent serve`) for triggers that are not CI events (Alertmanager) and for API-driven approvals. Both are built by `regent/bootstrap.py` from the same environment variables; the runtime code is identical.

## Consequences

- Value in the first week with no new infrastructure.
- Two entry points to keep in parity — enforced by sharing the bootstrap and the tests.
- The control plane's in-memory store (ADR-0009) is acceptable precisely because phase 1 does not depend on it.

## Alternatives considered

- **Control plane first** — weeks of platform work before the first review.
- **CI only, forever** — cannot receive alerts or offer an approval API.
