# Vision and business case

!!! tip "In plain words"
    Software teams spend a large share of their week on repetitive checks: reading other people's changes, figuring out why a build broke, fixing the same security misconfigurations, writing release notes. AI can do a lot of this — but an AI that is allowed to *do* things is also an AI that can do the wrong thing, at machine speed. Regent's bet is that the value comes from **automation with a governor**: agents that are useful precisely because their limits are explicit, checked and recorded.

## The problem

Delivery teams carry three kinds of load that grow with the codebase, not with the headcount:

1. **Review latency.** Pull requests wait for a human. The first pass (obvious bugs, security smells, missing tests) is mechanical but still takes a senior engineer's attention.
2. **Operational toil.** Failed pipelines get re-run blindly; dependency updates pile up; infrastructure findings from scanners are acknowledged and forgotten; incident first-response is a scramble to correlate an alert with "what changed".
3. **Security debt.** Shift-left scanners like CloudGuard-IaC *find* problems in the pull request. Someone still has to *fix* them.

Language models can take the first pass on all three. Without governance, though, an organisation faces a different set of problems:

- An agent that can merge can merge the wrong thing; one that can run commands can run the wrong command.
- Prompt injection: attacker-controlled text (a diff, a log line, a ticket) can steer an ungoverned agent.
- Confidential code and customer data flow to a third-party API with no classification.
- Nobody can answer the auditor's question: *what did the AI see, decide and do, and who allowed it?*
- Costs are unbounded and invisible.

## What Regent is

A platform where **agents act under mandates**. Three properties make it usable in an enterprise:

| Property | Meaning | Mechanism |
|---|---|---|
| **Bounded** | An agent can only do what its mandate lists, at the autonomy level it grants, within a budget. | `Mandate`, `RiskClass`, `BudgetMeter`, phase gate |
| **Verified** | No action follows an unverified output. Deterministic checks and an independent critic must both accept. | `verify()` in `regent/agents/verifier.py` |
| **Accountable** | Every run leaves a hash-chained audit trail: inputs seen (redacted), model and cost, decisions and the rule that fired, approvals. | `Ledger` |

## Goals

- Reduce review latency and operational toil on six concrete workflows (see the [agent catalogue](03-agent-catalogue.md)).
- Make autonomy a **configuration decision** taken by security and platform teams, reviewed in pull requests, not a property of the code.
- Keep the organisation's data classification honest: confidential content may reason on a local model; restricted content never leaves.
- Make every agent **testable offline** so that prompts, skills and mandates can change with the same confidence as code.
- Produce verifiable artefacts (signed images, SBOM, provenance) so the platform itself passes the supply-chain bar it enforces on others.

## Non-goals

- Replacing human review or human incident command. Every shipped mandate stops at "reversible" actions; irreversible ones (`L4_ACT`) are never granted.
- A general chat assistant. Agents are narrow and structured; there is no free-form conversation surface.
- A model-training platform. Regent consumes models; it does not fine-tune them.
- Multi-cloud abstraction of the infrastructure. The reference deployment targets Kubernetes and AWS-style primitives; the platform code is cloud-agnostic.

## Who it is for

| Stakeholder | What they get | What they own |
|---|---|---|
| **Platform / DevOps team** | A runtime for automations that used to be scripts and cron jobs, with policy, audit and cost built in. | The platform, tools, deployment. |
| **Security** | A single place to set what agents may do (mandates), the skills that encode the security baseline, the ledger. | Mandates, skills, threat model, kill switch. |
| **Developers** | Faster first-pass reviews, triaged CI failures, draft fixes for IaC findings, release notes that write themselves. | Accepting or dismissing findings; merging. |
| **Engineering management** | Measurable toil reduction; an answer to "are we using AI safely?". | Rollout decisions, budgets. |
| **Compliance / audit** | Evidence: who allowed what, what the model saw, what was done. | Reviewing the ledger and the mandate change history. |

## Value

The value drivers, with how to measure them. Ranges are **assumptions to validate on the organisation's own data**, not measurements — Regent ships metrics for exactly that purpose.

| Driver | Metric (formula) | Reasonable expectation after rollout |
|---|---|---|
| Review latency | median time from PR opened to first substantive review comment | First pass in minutes instead of hours; humans review with the mechanical findings already listed. |
| CI toil | share of failed runs classified without a human (`flaky` + `infrastructure` re-run automatically) | Typically 20–40 % of failures in mature pipelines are flaky/infra — the share Regent handles unattended. |
| IaC security debt | CRITICAL/HIGH CloudGuard findings open > 7 days | Findings get a draft PR the day they appear. |
| Incident MTTR | time from alert to first ranked hypothesis with evidence | Minutes; the on-call engineer starts from a hypothesis list and a drafted status update. |
| Dependency hygiene | median age of open bot PRs | Patch/minor bumps merged under policy within a day on low-risk repositories. |
| Cost of AI | `regent_llm_usd_total` by agent and repository | Bounded by mandate budgets; visible per repository. |

## Risks of doing nothing

- Teams adopt AI tooling individually (browser extensions, personal API keys): no classification, no audit, no shared rules.
- Scanner findings stay open; the security debt compounds.
- Review remains the bottleneck as delivery volume grows.

## Risks of doing it naively

| Naive approach | Failure mode | Regent's answer |
|---|---|---|
| Give an agent a GitHub token with write access and a broad prompt | It merges, closes, force-pushes; prompt injection steers it | Allow-listed tools with risk classes; autonomy ladder; verifier; phase gate |
| Paste diffs and logs into a SaaS model | Secrets and customer data leak | Redaction; data classes; local-model routing |
| Trust the model's own judgement on security fixes | Plausible but wrong fixes get merged | CloudGuard re-scan is the ground truth; draft PRs only |
| "It works in the demo" | Prompt drift breaks behaviour silently | Versioned prompts and skills; eval suite in CI |
| Unlimited API usage | Runaway costs | Hard per-run budgets; degradation; spend metrics |

## KPIs

| KPI | Formula | Target direction |
|---|---|---|
| Acceptance rate of findings | findings acted on ÷ findings posted | ↑ (signal quality) |
| Dismissal rate with reason | findings dismissed with a stated reason ÷ findings dismissed | ↑ (feeds evals) |
| Verifier rejection rate | `regent_verifications_total{verdict="rejected"}` ÷ total | Stable and low; a spike means a prompt or model regression |
| Denied runs | `regent_runs_total{status="denied"}` | Near zero after onboarding; each one is a mandate gap or an attack |
| Cost per completed run | `regent_llm_usd_total` ÷ `regent_runs_total{status="succeeded"}` | Within budget, trending down with caching |
| DORA lead time / change failure rate | standard definitions | Improve or stay flat — Regent must not add friction |

## Phased return

1. **Observe / advise** (weeks 1–4): agents only comment. Cost is API spend plus a platform engineer's time. Value: measured review latency drop and finding acceptance rate on a pilot repository.
2. **Propose** (month 2): IaC guardian opens draft PRs; release notes are drafted. Value: security debt starts closing without a human writing Terraform.
3. **Act, reversible** (month 3+): CI triage re-runs flaky jobs; dependency steward merges routine bumps on low-risk repositories. Value: unattended toil reduction, measured by runs completed without a human.

Each phase has exit criteria in the [operating model](10-operating-model.md). Widening a mandate is a pull request reviewed by security, so the organisation moves at the speed of its own evidence.
