# ADR-0009 — Run store: in memory now, Postgres for production

**Status:** Accepted (2026-09)

## Context

The control plane needs an index of runs for `GET /runs`, `GET /runs/{id}` and approvals. The ledger already holds every fact; the store is a convenience for queries and for resuming.

## Decision

`RunStore` in `regent/api/app.py` is an in-memory, lock-protected dictionary. For production it is replaced by a Postgres table (`run_id`, agent, repository, environment, status, started/finished, usage, output JSONB, pending_call JSONB) behind the same three methods (`put`, `get`, `list`). The ledger remains the source of truth; the store can be rebuilt from it.

## Consequences

- Phase 1 (CLI in CI) needs no database at all; the record is written to a JSON file (`--output`) and the ledger uploaded as an artefact.
- A restart of the in-memory control plane loses the index but not the audit trail; pending approvals must be re-triggered (acceptable in staging, not in production — hence Postgres).

## Alternatives considered

- **SQLite** — fine for one replica; the control plane is meant to scale horizontally.
- **Redis** — good for the index, poor as a durable store; Postgres does both.
