# ADR-0004 — The LLM gateway is the single door

**Status:** Accepted (2026-09)

## Context

If each agent called the model SDK directly, redaction, confidentiality checks, routing, budget and audit would be conventions, forgotten one at a time.

## Decision

`Gateway.complete(request, mandate, meter, audit)` is the only way to reach a model. In order: **redact** credentials in system and messages; **check** `request.classification` against `mandate.max_remote_class` and route to the local provider or raise `ConfidentialityViolation`; **route** the tier to a model (degrading on thin budgets); call the provider; **charge** the budget meter; **audit** an `llm.call` event (prompt id, model, tier, classification, redaction kinds, tokens, cost). `wrap_untrusted()` is the gateway's helper for marking external content.

## Consequences

- Agents cannot bypass a control even by mistake: `RunContext.llm()` is their only handle.
- The gateway is the one place to add a provider, a cache, a rate limiter or a new redaction pattern.
- Structured outputs are requested here (`output_config.format`), so every agent gets schema-valid JSON the same way.

## Alternatives considered

- **A network proxy (LiteLLM, API gateway)** — good for routing and keys, blind to classification and mandates, and adds a hop; can sit *behind* the gateway later.
- **Per-agent client code** — the failure mode the decision prevents.
