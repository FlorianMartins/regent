# Changelog

All notable changes to Regent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Mandates** — every agent runs under an explicit contract: autonomy level
  (`L0_OBSERVE` … `L3_ACT_REVERSIBLE`, `L4_ACT` never granted), tool allow-list,
  approval requirements, budget ceilings, data-classification limit and a kill switch.
  Resolved per (agent, repository, environment) from YAML, most specific wins.
- **Analyse → Verify → Act runtime** — read-only tools during analysis, deterministic
  checks plus an independent LLM critic before any action, autonomy as the ceiling of
  the act phase.
- **LLM gateway** — credential redaction, confidentiality routing (remote vs local
  provider), tier-based model routing with budget degradation, versioned prompts,
  Anthropic / OpenAI-compatible / replay providers.
- **Hash-chained audit ledger** (`regent ledger verify`) — tamper-evident JSON Lines.
- **Six agents** — `pr-reviewer`, `ci-triage`, `iac-guardian` (backed by
  CloudGuard-IaC), `incident-triage`, `dependency-steward`, `release-scribe`.
- **Skills** — versioned, content-addressed organisational know-how loaded into agents.
- **Evals** — offline eval cases with replay fixtures; `--live` for nightly runs.
- **Control-plane API** — GitHub and Alertmanager webhooks, runs, approvals, metrics.
- **Supply chain** — SBOM, SLSA provenance attestations, keyless cosign signatures,
  OpenSSF Scorecard, CodeQL, Trivy, gitleaks, CloudGuard-IaC and Conftest gates.
- **Deployment** — Docker Compose stack (API, Prometheus, Grafana, OTel collector),
  Kustomize base + overlays with Argo CD and Argo Rollouts, Terraform bootstrap for AWS.

[Unreleased]: https://github.com/FlorianMartins/regent/compare/main...HEAD
