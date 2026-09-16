# ADR-0006 — Hash-chained JSON Lines ledger

**Status:** Accepted (2026-09)

## Context

Auditors ask *what did the agent see, decide and do, and who approved it* — and need confidence the record was not edited afterwards. The record must work in a CI job (a file), in a cluster (shipped to a SIEM) and in an interview (readable with `jq`).

## Decision

`Ledger` appends one JSON object per event; each carries `seq`, `prev_hash` and `hash = sha256(seq, run_id, kind, at, data, prev_hash)` over a canonical serialisation. `Ledger.verify(path)` re-hashes the file and fails on the first altered, removed or reordered event. Event data is bounded (400 chars) and redacted. Event kinds are fixed (`run.started`, `tool.decision`, `tool.call`, `llm.call`, `analysis`, `verification`, `approval`, `run.finished`, …).

## Consequences

- Tamper-**evident**, not tamper-proof: an attacker who rewrites the whole file from genesis produces a valid chain. Ship to write-once storage (object lock, SIEM) for that.
- No database needed for the audit trail; a database index (ADR-0009) is a convenience beside it.
- Plain text means the format is stable and greppable forever.

## Alternatives considered

- **Database rows only** — editable by anyone with write access; no offline verification.
- **External notarisation / blockchain** — heavy; object lock on the shipped copy achieves the same guarantee.
- **Structured logs only** — no chain, no verification command.
