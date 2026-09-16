# ADR-0001 — Governed autonomy via mandates

**Status:** Accepted (2026-09)

## Context

An agent that can call tools can do damage at machine speed, and the text it reads (diffs, logs, tickets) is attacker-controllable. Enterprises need to answer *what may this agent do, where, at whose cost, and who allowed it* — and to change the answer without a code deployment.

## Decision

Every run executes under a **mandate**: a YAML document resolved per `(agent, repository, environment)` that fixes the **autonomy level** (`L0_OBSERVE` … `L3_ACT_REVERSIBLE`; `L4_ACT` exists but is never granted and rejected by `policy-check`), an **allow-list** of tools, tools that **require approval**, a **budget**, a **model tier**, a **confidentiality ceiling** and the **verification mode**. Every tool declares a **risk class** (`READ` … `DESTRUCTIVE`); a call is allowed only if the class is within the autonomy, and the rule that decided is written to the ledger. Mandates live in `policies/mandates/`, owned by security through CODEOWNERS.

## Consequences

- Widening what an agent can do is a reviewed configuration change, visible in Git and in every `run.started` event (`source`).
- Agents are written without knowing their permissions; the same code runs at L0 on one repository and L3 on another.
- A tool with a new risk class is a visible design change.
- Cost: a second vocabulary (mandate fields) to learn; `regent policy-check` and the docs keep it honest.

## Alternatives considered

- **Permissions in code / prompts** — invisible to reviewers, changed by deployments, and a prompt is not an enforcement point.
- **A single global permission set** — cannot express "advise on payments, act on internal tools".
- **Per-tool RBAC only** (no autonomy ladder) — misses the ordering that makes rollout phases simple (L0 → L3).
