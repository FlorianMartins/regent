# Glossary

!!! tip "In plain words"
    Every word that might be new, in one or two sentences each. Terms specific to Regent come first, then the industry vocabulary.

## Regent terms

| Term | Definition |
|---|---|
| **Agent** | One bounded automation (review a PR, triage a failed build…). It reasons through a language model and acts only through tools. Six are shipped. |
| **Analyse → verify → act** | The three phases of every run. Analyse reads and reasons (READ tools only); verify checks the output (deterministic checks + critic); act performs the allowed actions. |
| **Autonomy level** | How far an agent may go on its own: `L0_OBSERVE`, `L1_ADVISE`, `L2_PROPOSE`, `L3_ACT_REVERSIBLE`, `L4_ACT` (never granted). |
| **Budget** | Hard per-run ceilings in the mandate: model calls, tool calls, tokens, dollars, seconds. |
| **Critic** | The second model call, with a different prompt (`verifier@1`), that accepts or rejects an agent's output. Part of the verifier. |
| **Data class** | Confidentiality of a piece of data: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`. Every tool result carries one; a run's class only goes up. |
| **Deterministic check** | A test written in code (not by a model) that an output must pass, e.g. `findings_cite_lines`, `cloudguard_clean_after_fix`. |
| **Dry run** | A run where write tools describe what they would do instead of doing it (`--dry-run`). |
| **Eval case** | A YAML file describing a fake world, scripted model answers and assertions on the run; the unit test of a prompt. |
| **Gateway** | The single component through which every model call passes: redaction, confidentiality check, routing, budget, audit. |
| **Kill switch** | `kill_switch: true` in a mandate; the agent is denied everywhere, immediately. |
| **Ledger** | Append-only JSON Lines audit file where each event carries the SHA-256 of the previous one. `regent ledger verify` detects any change. |
| **Mandate** | The YAML contract an agent runs under: autonomy, allowed tools, approvals, budget, tier, scopes, confidentiality ceiling, verification mode. |
| **Phase gate** | A runtime rule: during analysis only READ tools pass, whatever the mandate grants. |
| **Prompt id** | `name@version` of a prompt template (e.g. `pr_reviewer@1`); recorded with its sha256 in the ledger. |
| **Replay provider** | A model backend that answers from fixtures; makes tests and evals deterministic, offline and free. |
| **Risk class** | What a tool can do to the world: `READ`, `ADVISE`, `PROPOSE`, `ACT_REVERSIBLE`, `DESTRUCTIVE`. Compared to the autonomy level. |
| **Run** | One execution of one agent under one mandate; its summary is a `RunRecord` with a status. |
| **Skill** | A versioned `SKILL.md` with the organisation's rules for a domain (e.g. `terraform-baseline`), composed into the agent's system prompt. |
| **Tier** | `fast`, `balanced`, `deep` — a promise of capability and cost that the router turns into a concrete model. |
| **Tool** | A named capability with a declared risk class and data class; the only way an agent touches the world (e.g. `github.create_review`). |
| **Untrusted data** | External content (diffs, logs, alerts, PR text) wrapped in `<untrusted_data>` tags so the model treats it as data, not instructions. |
| **Verifier** | Deterministic checks plus the critic; runs between analyse and act. Modes: `required`, `advisory`, `none`. |

## Industry terms

| Term | Definition |
|---|---|
| **ADR** (Architecture Decision Record) | A short document recording one decision, its context, alternatives and consequences. |
| **Argo CD** | A Kubernetes controller that keeps a cluster in sync with manifests stored in Git (GitOps). |
| **Argo Rollouts** | A Kubernetes controller for canary and blue/green deployments with automated analysis. |
| **CI/CD** | Continuous integration (every change is built and tested automatically) / continuous delivery (and can be deployed automatically). |
| **CODEOWNERS** | A GitHub file that names who must review changes to given paths. |
| **Conftest** | A tool that tests configuration files (Kubernetes YAML, Terraform plans) against OPA policies. |
| **cosign** | A Sigstore tool to sign and verify container images; "keyless" mode uses an OIDC identity instead of a private key. |
| **CVE** | A public identifier for a known vulnerability in a specific piece of software. |
| **CWE** | A catalogue of *types* of weakness (e.g. CWE-798, hard-coded credentials). |
| **DORA metrics** | Four delivery metrics: lead time for changes, deployment frequency, change failure rate, time to restore service. |
| **DPA** | Data-processing agreement: the contract that says what a provider may do with the data you send. |
| **GitOps** | Operating infrastructure by changing files in Git and letting a controller apply them. |
| **HMAC** | A signature computed with a shared secret; GitHub signs webhooks with it so the receiver can check they are genuine. |
| **HPA / PDB** | Horizontal Pod Autoscaler (scales pods on load) / Pod Disruption Budget (limits how many pods may be down at once). |
| **IaC** (Infrastructure as Code) | Describing servers, networks and buckets in files (Terraform) instead of clicking in a console. |
| **Kustomize** | A tool that assembles Kubernetes YAML from a base plus per-environment overlays. |
| **LLM** | Large language model — the AI that reads and writes text (here, Claude). |
| **LLMOps** | The practices for operating LLM-based systems: prompt versioning, evaluation, monitoring, cost control. |
| **MTTR** | Mean time to restore: how long an incident lasts on average. |
| **OIDC** | OpenID Connect; here, the mechanism by which a CI job proves its identity to a cloud or to Sigstore without stored keys. |
| **OPA / Rego** | Open Policy Agent, a policy engine, and its language. |
| **OpenTelemetry (OTel)** | A vendor-neutral standard and SDK for traces, metrics and logs. |
| **OWASP LLM Top 10** | The ten most important risk categories for applications built on language models (prompt injection, excessive agency…). |
| **Prometheus / Grafana** | A metrics database with its query language PromQL / a dashboard tool. |
| **Prompt injection** | An attack where text the model reads (a diff, a ticket) contains instructions that hijack it. |
| **SARIF** | A standard JSON format for static-analysis results; GitHub renders it in the Security tab. |
| **SAST** | Static application security testing: scanning source code for vulnerability patterns. |
| **SBOM** | Software bill of materials: the list of every package inside a piece of software. |
| **SIEM** | Security information and event management: the system that collects and searches logs for security purposes. |
| **SLSA** | Supply-chain Levels for Software Artifacts: a framework of levels describing how trustworthy a build is; provenance is its core artefact. |
| **STRIDE** | A threat-model checklist: Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege. |
| **Structured output** | Asking the model to answer in JSON matching a schema, so the answer can be validated and used by code. |
| **Terraform** | The most common IaC tool; files in HCL describe cloud resources. |
| **Trivy / Syft / Grype** | A vulnerability scanner for images / an SBOM generator / an SBOM vulnerability scanner. |
| **Webhook** | An HTTP call one system makes to another when something happens (GitHub → Regent when a PR opens). |
