# Technology radar

!!! tip "In plain words"
    Every tool in Regent was chosen against alternatives. This page lists, layer by layer, what was picked, what was considered, why, and what it costs. Nothing here is a fashion choice; each line has a reason that a reviewer can disagree with.

## Language and libraries

| Layer | Chosen | Alternatives | Why | Trade-offs |
|---|---|---|---|---|
| Language | **Python 3.11+** | Go, TypeScript | The team's DevSecOps tooling (CloudGuard-IaC) is Python; the model SDKs are first-class; readability for auditors | Slower than Go for a hot path that does not exist here (runs wait on I/O) |
| Models & validation | **Pydantic v2** | dataclasses, attrs | Frozen models, JSON schema generation for structured outputs, validation of model answers | Schema tweaks (`_strict`) needed for strict output |
| CLI | **Typer + Rich** | argparse, Click | Same as CloudGuard; typed options; readable tables | Rich tables wrap in narrow terminals (tests set `COLUMNS`) |
| API | **FastAPI** | Flask, Django REST | Pydantic-native, background tasks, OpenAPI for free | Async runtime; kept optional (`[api]` extra) |
| HTTP | **httpx** | requests | Same client for GitHub and local models; mockable transport | — |

## Models and orchestration

| Layer | Chosen | Alternatives | Why | Trade-offs |
|---|---|---|---|---|
| Provider | **Anthropic Claude via the official SDK** (tiers `claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5`) | OpenAI, Gemini, Bedrock/Vertex | Structured outputs by schema, adaptive thinking, prompt caching, strong instruction hierarchy for the untrusted channel | Provider concentration; mitigated by the `Provider` protocol |
| Local models | **OpenAI-compatible endpoint** (vLLM, Ollama, TGI, LiteLLM) | Provider-specific local SDKs | One wire format covers every serving stack; needed for RESTRICTED data | Quality gap on hard tasks; that is why it is for confidentiality, not cost |
| Agent runtime | **Custom, ~1 500 lines** | LangChain, LlamaIndex, CrewAI, AutoGen, Semantic Kernel | Auditability: every decision point is readable code with a test; no hidden tool loop; no framework-shaped attack surface; no lock-in | We maintain it; no ecosystem of prebuilt tools (deliberate) — [ADR-0003](adr/ADR-0003-no-agent-framework.md) |
| Agent loop | **Single-pass analyse → verify → act** | Autonomous ReAct loops | Bounded cost and behaviour; the mandate is enforceable per phase | Less "clever"; tasks that need exploration are split into tools |
| Durable execution | **Not shipped; Temporal planned** | Argo Workflows, Step Functions, Celery | Approvals are re-runs today ([ADR-0010](adr/ADR-0010-approvals-by-rerun.md)); Temporal gives suspended workflows, retries and history when the control plane grows | Operational weight of a Temporal cluster; not justified at phase 1–2 |
| Prompt management | **Markdown files with front-matter, versioned in Git** | Prompt SaaS, database | Reviewable in PRs, hash in the ledger, no runtime dependency | No UI for non-engineers |
| Evals | **YAML cases + replay provider + pytest** | promptfoo, LangSmith, Braintrust | Zero external dependency; runs in any CI; deterministic | Fewer built-in graders; live runs are a nightly job, not a UI |

## Policy and audit

| Layer | Chosen | Alternatives | Why | Trade-offs |
|---|---|---|---|---|
| Agent policy (mandates) | **In-process engine, YAML** | OPA/Rego, Cedar | Needs the run context (phase, approvals, budget); unit-testable; readable by non-Rego reviewers | Two policy languages in the repo — [ADR-0007](adr/ADR-0007-policy-engine.md) |
| Admission policy | **OPA / Conftest (Rego)** | Kyverno | Industry standard for Kubernetes and Terraform plans; runs in CI and as Gatekeeper | Rego learning curve |
| Audit | **Hash-chained JSON Lines** | Database table only, blockchain | Tamper-evident, greppable, shippable to any SIEM, verifiable offline | Not tamper-*proof* without a write-once sink; a DB index sits beside it in prod — [ADR-0006](adr/ADR-0006-hash-chained-ledger.md) |
| Run store | **In memory now, Postgres in prod** | SQLite, Redis | Simplicity first; the ledger is the source of truth | Restarts lose the in-memory index — [ADR-0009](adr/ADR-0009-run-store.md) |

## Delivery and infrastructure

| Layer | Chosen | Alternatives | Why | Trade-offs |
|---|---|---|---|---|
| CI | **GitHub Actions** | GitLab CI, Jenkins, Buildkite | Where the code and the agents' events live; OIDC to cloud; attestations built in | Vendor coupling for CI only |
| Manifests | **Kustomize** | Helm | Plain YAML, overlays without templating; policy tools read it directly | Less packaging ergonomics than a chart |
| GitOps | **Argo CD** | Flux | App-of-apps, UI for reviewers, Argo Rollouts integration | Another controller to run |
| Progressive delivery | **Argo Rollouts** | Flagger | Same family as Argo CD; analysis on Prometheus metrics | — |
| IaC | **Terraform** | Pulumi, CDK, OpenTofu | Ubiquitous; CloudGuard-IaC parses it; plans checkable by Conftest | HCL is not a programming language (a feature here) |
| Local stack | **Docker Compose** | kind, Tilt | One command to get API + metrics + traces | Not Kubernetes; the k8s overlay is the reference |

## Observability

| Layer | Chosen | Alternatives | Why |
|---|---|---|---|
| Metrics | **Prometheus client**, Grafana | StatsD, vendor agents | Standard; PromQL is also a tool the incident agent can use |
| Traces | **OpenTelemetry**, OTLP/HTTP | Vendor SDKs | Vendor-neutral; optional dependency |
| Logs/audit | Stdout + ledger → Loki/SIEM | — | Join on `run_id` |

## Security tooling

| Tool | Role | Why this one |
|---|---|---|
| **CloudGuard-IaC** | Terraform/Dockerfile misconfigurations; ground truth for the IaC guardian | Explains why and how to fix; SARIF; the author's own scanner |
| **Trivy** | Container image CVEs | Fast, offline DB, SBOM-aware |
| **Semgrep** | Extended SAST (advisory) | Rule registry; kept advisory because it needs the network |
| **Bandit** | Python SAST (blocking) | Zero network, catches the classics |
| **pip-audit** | Dependency advisories | Official PyPA tool |
| **gitleaks** | Secrets in history | Broad pattern base, fast |
| **Syft / Grype** | SBOM generation / SBOM scanning | Anchore's pair; SPDX and CycloneDX |
| **cosign** (Sigstore) | Keyless signing with the workflow's OIDC identity | No keys to manage or leak |
| **SLSA provenance** (`actions/attest-build-provenance`) | Build provenance | Verifiable with `gh attestation verify` |
| **OpenSSF Scorecard**, **CodeQL**, **Dependabot** | Repo hygiene, semantic scanning, updates | Free on GitHub; visible as badges |

## Considered and not shipped

| Item | Status | Reason |
|---|---|---|
| **Temporal** for durable runs | Phase 3 | Approvals by re-run are enough for L1–L3; Temporal earns its cost when runs must wait hours and resume |
| **Backstage** developer portal | Phase 3 | The catalogue is Markdown today; a portal plugin would read the same API (`/agents`, `/runs`) |
| **Vector store / RAG** | Not planned | No retrieval use case in the six workflows; if added, its content is untrusted data |
| **Fine-tuning** | Not planned | Skills and prompts carry the organisation's rules; cheaper and auditable |
| **Multi-agent orchestration** (agents calling agents) | Not planned | Each workflow is one agent plus the verifier; chains multiply the blast radius |
