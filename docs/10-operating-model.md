# Operating model

!!! tip "In plain words"
    A platform is not just software; it is a way of working. Who runs it, who decides what the agents may do, how a team starts using it, how autonomy is increased step by step, what happens at 3 a.m. when it misbehaves. This page is the organisational half of Regent.

## Team topology

| Team | Owns | Interfaces |
|---|---|---|
| **Platform team** (owner of Regent) | The runtime, tools, deployment, prompts, evals, on-call | Publishes the agent catalogue; accepts onboarding requests; reviews mandate PRs with security |
| **Security** | Mandates (approval authority), skills that encode baselines, threat model, ledger reviews, kill switch | CODEOWNERS on `policies/` and `regent/skills/library/` |
| **Product / stream-aligned teams** | Their repositories' overrides (within what security allows), dismissals, approvals of pending runs | Open onboarding PRs; give feedback that becomes eval cases |
| **FinOps / management** | Budgets per repository, rollout decisions | Read the spend dashboards |

This is a *platform team* in the Team Topologies sense: it reduces cognitive load for stream-aligned teams and exposes a self-service interface (a YAML file and a CLI), not tickets.

## Onboarding a repository

1. Team opens a PR adding an override in `policies/mandates/` scoped to the repository, at **L0/L1** for every agent they want, `verification: required`.
2. Platform installs the GitHub App on the repository (or the team adds the CI workflow calling `regent run`).
3. `regent policy-check` and the eval suite pass in CI; security approves the PR.
4. Two weeks at L1: measure acceptance rate and verifier rejection rate.
5. Team requests the next rung per agent with the numbers; security reviews.

Full checklist: [runbook](runbooks/onboard-a-repository.md).

## Rollout roadmap (per agent, per repository)

| Phase | Autonomy | Exit criteria to move up |
|---|---|---|
| 0 — Observe | `L0_OBSERVE`, dry run, ledger only | Runs succeed for two weeks; cost within forecast; no `denied` surprises |
| 1 — Advise | `L1_ADVISE` | Finding acceptance ≥ 60 %; verifier rejection < 10 %; developers asked for it to stay |
| 2 — Propose | `L2_PROPOSE` | ≥ 80 % of draft PRs merged with ≤ minor edits over a month |
| 3 — Act, reversible | `L3_ACT_REVERSIBLE` (re-runs, routine merges), first with `requires_approval`, then without on low-risk repositories | Zero reverts of agent merges in a month; on-call reports no noise |
| 4 | Never | — |

Moving *down* a rung needs no review (platform on-call can do it); moving *up* is a PR with the numbers attached.

## Maturity model

| Level | Description |
|---|---|
| 1 — Ad hoc | Individuals use AI tools with personal keys; no audit, no rules |
| 2 — Governed advice | Regent at L1 on pilot repositories; ledger shipped; budgets set |
| 3 — Governed proposals | L2 for IaC and releases; evals gate prompt changes; dashboards in use |
| 4 — Governed action | L3 on low-risk repositories with approvals; live evals nightly; chargeback |
| 5 — Optimising | Golden datasets from dismissals feed evals monthly; local models for RESTRICTED; Temporal-backed durable runs; developer portal integration |

## On-call for the platform

- Pager on: control plane down (`/readyz` failing), spend alert, verifier rejection spike, ledger verification failure.
- First actions are runbooks: [kill switch](runbooks/kill-switch.md), [budget exceeded](runbooks/budget-exceeded.md), [agent misbehaving](runbooks/agent-misbehaving.md), [ledger verification](runbooks/ledger-verification.md).
- A misbehaving agent is a **product incident** for the platform team, not a security incident for the consuming team — unless data classification was breached, which pages security.

## Training and communication

- 30-minute onboarding for developers: what the comments mean, how to dismiss with a reason, that the agent never approves.
- Mandate literacy for security: the ladder, the rules order, `policy-check`.
- Every widening of autonomy is announced with the numbers that justified it.

## KPIs and DORA

| KPI | Source |
|---|---|
| Lead time for changes, deployment frequency, change failure rate, MTTR | Existing DORA tooling; Regent must move them the right way or stay neutral |
| Finding acceptance / dismissal-with-reason rates | GitHub, exported |
| Share of CI failures handled unattended | `regent_runs_total{agent="ci-triage",status="succeeded"}` and the `category` in analyses |
| IaC findings closed via draft PRs | CloudGuard reports before/after |
| Cost per completed run | `regent_llm_usd_total` ÷ succeeded runs |
| Denied runs and verifier rejections | `regent_runs_total{status="denied"}`, `regent_verifications_total{verdict="rejected"}` |

## When an agent misbehaves

1. Kill switch (seconds).
2. Read the ledger for the run: prompt id, skills, mandate source, what it saw (redacted), what the checks and the critic said.
3. Reproduce offline with a replay fixture built from the ledger; write the eval case that fails.
4. Fix the prompt, skill, check or mandate; the eval passes; ship.
5. Re-enable; watch the rejection rate.
