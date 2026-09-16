# Architecture Decision Records

!!! tip "In plain words"
    An ADR is a one-page note that says: *we had to decide something, here were the options, here is what we picked and why, here is what it costs us.* Reading them in order tells the story of why Regent looks the way it does. Decisions are never edited after acceptance; a change is a new ADR that supersedes the old one.

| ADR | Decision | Status |
|---|---|---|
| [0001](ADR-0001-governed-autonomy-via-mandates.md) | Agents run under explicit mandates with an autonomy ladder | Accepted |
| [0002](ADR-0002-analyse-verify-act.md) | Every run is analyse → verify → act, with an independent critic | Accepted |
| [0003](ADR-0003-no-agent-framework.md) | Custom runtime; no agent framework | Accepted |
| [0004](ADR-0004-llm-gateway-single-door.md) | One gateway for every model call: redaction, classification, routing | Accepted |
| [0005](ADR-0005-model-tiers.md) | Mandates name tiers, not models | Accepted |
| [0006](ADR-0006-hash-chained-ledger.md) | Hash-chained JSON Lines audit ledger | Accepted |
| [0007](ADR-0007-policy-engine.md) | Agent policy in-process (YAML); OPA/Conftest at admission | Accepted |
| [0008](ADR-0008-prompts-and-skills-as-code.md) | Prompts and skills are versioned code | Accepted |
| [0009](ADR-0009-run-store.md) | Run store in memory now, Postgres for production | Accepted |
| [0010](ADR-0010-approvals-by-rerun.md) | Approvals by re-run with pre-approved tools; Temporal later | Accepted |
| [0011](ADR-0011-phase-gate.md) | Phase gate: no writes during analysis | Accepted |
| [0012](ADR-0012-data-classification.md) | Data classification and local-model routing | Accepted |
| [0013](ADR-0013-cloudguard-ground-truth.md) | CloudGuard-IaC is the ground truth for IaC fixes | Accepted |
| [0014](ADR-0014-pipeline-embedded-first.md) | Pipeline-embedded topology first, control plane second | Accepted |
| [0015](ADR-0015-supply-chain-attestations.md) | SBOM, keyless signature and SLSA provenance on releases | Accepted |
| [0016](ADR-0016-offline-evals.md) | Offline replay evals in CI, live evals nightly | Accepted |

Template: Status · Context · Decision · Consequences · Alternatives considered.
