# ADR-0012 — Data classification and local-model routing

**Status:** Accepted (2026-09)

## Context

Diffs are confidential; alert payloads may carry customer identifiers; some repositories are under regulatory constraints. "Do not send that to a SaaS model" must be enforceable, not a guideline.

## Decision

`DataClass ∈ {PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED}`. Every `ToolSpec` declares the classification of what it returns; `RunContext.untrusted()` assigns one to wrapped inputs; the run's classification is the **maximum seen so far** and never decreases. The mandate's `max_remote_class` is the ceiling for the remote provider. Above it, the gateway uses the **local provider** (`REGENT_LOCAL_URL`, OpenAI-compatible, `locality = local`) or raises `ConfidentialityViolation` — fail closed. Redaction runs regardless of class.

## Consequences

- Confidentiality is a property of data and a field of policy, both auditable (`classification` in `tool.call` and `llm.call`).
- Organisations without a local model simply cannot run RESTRICTED workflows — by design.
- Mis-declared tool classifications are a code review concern; the default is `INTERNAL`, and read tools on code/logs declare `CONFIDENTIAL`.

## Alternatives considered

- **Everything remote with a DPA** — acceptable for many organisations for CONFIDENTIAL; not for RESTRICTED.
- **Everything local** — quality gap on hard tasks; cost of serving; the routing gives both.
