# ADR-0007 — Agent policy in-process; OPA/Conftest at admission

**Status:** Accepted (2026-09)

## Context

Two different questions: *may this agent call this tool now?* (needs the run's phase, approvals, budget and mandate) and *may this manifest or plan be deployed?* (needs the artefact). OPA/Rego is the standard for the second; forcing the first into Rego would require shipping the run context to a sidecar and teaching every reviewer Rego.

## Decision

Agent mandates are YAML evaluated by `regent/core/policy.py` in-process: a fixed, documented rule order (`kill_switch`, `denied`, `not_allowed`, `destructive`, `autonomy`, `approval`, `allow`), unit-tested, returning the rule name for the ledger. `regent policy-check` validates invariants. Kubernetes manifests and Terraform plans are checked by **Conftest/OPA** policies in `policies/rego/` in CI, and by Gatekeeper at admission.

## Consequences

- Two policy languages in the repository, each where it is idiomatic.
- The agent engine is readable by a security reviewer who does not write Rego.
- If a future need requires cross-system policy (e.g. the same rule for agents and admission), export mandates to Rego data; the evaluation order is simple enough to port.

## Alternatives considered

- **OPA for everything** — context plumbing, an extra process in CI jobs, Rego literacy for every mandate review.
- **Cedar** — good model, less ecosystem for CI/Kubernetes.
- **No admission policy** — the platform's own manifests would not be checked; rejected.
