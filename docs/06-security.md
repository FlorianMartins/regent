# Security

!!! tip "In plain words"
    An AI agent that reads text from the outside world and can push buttons is a new kind of target: an attacker does not need to break in, they only need to write something the agent will read. Regent's defence has three layers: the agent can only push the buttons its mandate lists; whatever it reads is marked as *data, not orders*; and everything it does is checked by a second opinion and written down. On top of that, the platform itself is built the way it asks others to build: scanned, signed, with a bill of materials.

## Threat model (STRIDE)

Assets: the organisation's source code and logs (confidentiality), its repositories and clusters (integrity, availability), its LLM spend (availability), the ledger (integrity), credentials held by the platform.

| Threat | Example | Control in Regent |
|---|---|---|
| **S**poofing | Forged webhook starts a run | HMAC `X-Hub-Signature-256` with `GITHUB_WEBHOOK_SECRET`; bearer token for Alertmanager; no secret → `503`, bad → `401` |
| | Someone impersonates the platform on GitHub | GitHub App / job token with least privilege; every write signed "🤖 Regent" and traceable to a `run_id` |
| **T**ampering | Attacker edits the audit trail | Hash-chained ledger; `regent ledger verify`; ship to a write-once store |
| | Prompt injection in a diff, log, ticket or alert steers the agent (OWASP LLM01/LLM08) | `wrap_untrusted()` channel; prompt rules; verifier sees the output as data; deterministic checks; allow-listed tools |
| | Malicious mandate widening | CODEOWNERS; `policy-check` invariants (no L4, no wildcard, budget cap) |
| **R**epudiation | "The AI did it, nobody approved" | `approval` events with approver; `run.started` records mandate `source`, trigger actor |
| **I**nformation disclosure | Secrets in a diff reach the provider | Redaction of 12 credential families before every call; kinds logged, values never |
| | Confidential or regulated content reaches a SaaS model | `DataClass` on every tool result; `max_remote_class`; local-model routing; `ConfidentialityViolation` fails closed |
| | Ledger leaks content | Ledger stores bounded, redacted summaries (400 chars), not raw prompts |
| **D**enial of service | Runaway agent loops, huge inputs | `Budget` ceilings on calls, tokens, USD, duration; diff/log truncation; provider retries bounded |
| | Webhook flood | Background tasks bounded by the deployment (HPA, rate limit at ingress) |
| **E**levation of privilege | Agent runs an arbitrary command | No shell: allow-listed argv prefixes, refused metacharacters and flags, scrubbed environment, timeout |
| | Agent writes outside its checkout | Workspace jail (`fs.*` refuse path escapes) |
| | Agent acts during analysis | Phase gate |
| | Destructive action | `DESTRUCTIVE` risk class needs L4, never granted |

## OWASP Top 10 for LLM applications — mapping

| OWASP | Risk | Mitigation, with the code that implements it |
|---|---|---|
| **LLM01** Prompt injection | Untrusted text steers the agent | `regent/gateway/gateway.py::wrap_untrusted` wraps diffs, logs, PR bodies, alerts in `<untrusted_data label= classification=>` (closing tags inside are neutralised); every prompt states these are data; the verifier (`regent/agents/verifier.py`) re-reads the *output* as untrusted data; tools are allow-listed so an injected "merge this" has no tool to call. Eval case `evals/cases/pr_reviewer_prompt_injection_in_diff.yaml` |
| **LLM02** Sensitive information disclosure | Secrets or personal data in prompts or outputs | `regent/core/redaction.py` before every call (`Gateway.complete`); `DataClass` per tool result raised through the run; `max_remote_class` + local provider (`OpenAICompatibleProvider`); ledger summaries redacted |
| **LLM03** Supply chain | Compromised model, SDK or dependency | Official Anthropic SDK pinned by range; `pip-audit`, Dependabot; the platform's own image carries SBOM + provenance + signature ([attestations](12-certifications-and-attestations.md)) |
| **LLM04** Data and model poisoning | Not applicable: Regent does not train or fine-tune. Skills and prompts are code-reviewed and versioned (their sha256 is in the ledger) | |
| **LLM05** Improper output handling | Model output executed or rendered unsafely | Outputs are **structured** (`output_config.format` JSON schema, validated by Pydantic); they are rendered as Markdown comments, never executed; commands come from the allow-list, never from output text |
| **LLM06** Excessive agency | The agent can do more than the task needs | Mandate allow-lists; risk classes vs autonomy; phase gate; `requires_approval`; dry run; kill switch; no `DESTRUCTIVE` tool exists |
| **LLM07** System prompt leakage | Secrets in the system prompt, or the prompt revealed | System prompts contain no secrets (they are public files in `regent/prompts/`); redaction covers the system text too |
| **LLM08** Vector and embedding weaknesses | Not applicable: no retrieval-augmented store. If one is added, its content must go through `wrap_untrusted()` like any other external data | |
| **LLM09** Misinformation | Confident but wrong output | Evidence fields required in every output; deterministic checks (`findings_cite_lines`, `cloudguard_clean_after_fix`, `classification_has_quotes`…); critic; humans still decide |
| **LLM10** Unbounded consumption | Cost and latency blow-up | `Budget` per run enforced by `BudgetMeter`; router degrades tiers; input truncation; metrics `regent_llm_usd_total` |

## Lessons imported

From **CloudGuard-IaC**: credentials have recognisable shapes (`AKIA…`, `ghp_…`, PEM blocks) — cheap to catch, expensive to miss; a scanner must explain *why* and *how to fix*; a tool must be able to block a pipeline with a clear exit code. Regent's redaction patterns, the `why`/`remediation` fields it feeds the model, and the CLI exit codes (0/1/2) come from there. And the scanner itself is the ground truth for the IaC guardian.

From the **LLM Security Lab**: untrusted data concatenated into the system prompt is how injection lands (LLM01); over-broad retrieval leaks internal data (LLM02); an agent that auto-executes high-impact tools is the vulnerability (LLM06); input caps and rate limits are not optional (LLM10). Regent's untrusted channel, data classes, mandates and budgets are those fixes, generalised.

## Secrets management

| Secret | Held by | How it reaches Regent | Rotation |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Secret manager (AWS Secrets Manager / Vault) → Kubernetes Secret via External Secrets Operator; GitHub Actions secret for CI | Environment variable; never an argument, never in the ledger | [Runbook](runbooks/rotate-credentials.md) |
| `GITHUB_TOKEN` | In CI: the job token, scoped by `permissions:`; in the control plane: a GitHub App installation token (short-lived) | Environment | App tokens expire in 1 h |
| `GITHUB_WEBHOOK_SECRET`, `ALERTMANAGER_WEBHOOK_TOKEN` | Secret manager | Environment | Rotate with the webhook configuration |
| Cloud credentials for Terraform | None stored: GitHub OIDC → IAM role assumption in CI | Federated | No long-lived keys |

Regent never puts a secret in a prompt, a tool argument or a ledger line; redaction is the safety net, not the design.

## Identity of the agents (GitHub App permissions)

| Permission | Level | Needed by |
|---|---|---|
| Pull requests | read & write | reviews, comments, labels, draft PRs, merges (steward) |
| Contents | read; write only on repositories where `iac-guardian` may push branches | diffs, files; fix branches |
| Issues | read & write | triage issues, incident issues |
| Actions | read & write | run/job logs; re-run failed jobs |
| Metadata | read | everything |
| Checks, Deployments, Administration | **none** | — |

One installation per organisation; the ledger's `run_id` in every comment ties GitHub's audit log to Regent's.

## Sandboxing

Today (`regent/tools/sandbox.py`): agents get **named commands** (`exec.git.status`, `exec.pytest`, `exec.terraform.validate`, `exec.kubectl.rollout.status`…), each a fixed argv prefix; agent-supplied arguments are validated (no `; & | \` $ < >`, no free flags), never passed through a shell; environment scrubbed to `PATH HOME LANG LC_ALL TMPDIR TERM`; timeout; output bounded.

Production target: the same tool interface backed by **ephemeral job pods** on a hardened runtime (gVisor or Kata Containers), no network except the allow-listed egress, read-only root filesystem, the checkout mounted as the only writable volume. The interface does not change; only the executor does.

## Supply chain

| Control | What it gives | Where |
|---|---|---|
| SBOM (Syft, SPDX/CycloneDX) | Inventory of what is in the image | Attached to the release and as an attestation |
| Vulnerability scan (Trivy) on the image; `pip-audit` on dependencies | Known CVEs fail the pipeline above the threshold | CI |
| SLSA provenance (`actions/attest-build-provenance`) | Proof of *which* workflow built *which* commit into *which* digest | Attestation on the image / artefact |
| Keyless signature (cosign, Sigstore, GitHub OIDC identity) | The image was signed by this repository's workflow, not by a person's laptop | Registry (GHCR) |
| Pinned, Dependabot-maintained GitHub Actions | No mutable `@main` references | Workflows |
| CloudGuard-IaC on `infra/`, Conftest/OPA on manifests and plans | The platform's own infrastructure passes the same gates | CI |
| OpenSSF Scorecard, CodeQL | Repository hygiene and semantic code scanning | Badges, Security tab |

Targeted level: **SLSA Build L2** (hosted build, signed provenance). L3 needs isolated, non-reusable build environments and provenance non-falsifiable by the build's own steps; GitHub's reusable-workflow generators can get there and are the next step once the release process stabilises. [ADR-0015](adr/ADR-0015-supply-chain-attestations.md).

## Network

- Egress from the control plane restricted by NetworkPolicy to: GitHub API, the LLM provider's endpoint, the local model service, Prometheus, the OTel collector.
- Ingress only from the ingress controller; webhooks terminate TLS there.
- CI jobs: the runner's egress; the API key and token are the only secrets present.

## Confidentiality tiers with examples

| Class | Examples | Remote model allowed? (default mandates) |
|---|---|---|
| `PUBLIC` | Open-source code, public issue text | Yes |
| `INTERNAL` | PR titles and descriptions, commit messages, workflow metadata, labels | Yes |
| `CONFIDENTIAL` | Source diffs, file contents, job logs, sandbox output | `pr-reviewer`, `ci-triage`, `iac-guardian`: yes (the organisation accepted the provider's data-processing terms); `incident-triage`, `dependency-steward`, `release-scribe`: no |
| `RESTRICTED` | Alert payloads (may carry customer identifiers), anything under legal hold | Never remote; local model or the run fails |

The classification of a run only goes up: one RESTRICTED tool result makes every later model call RESTRICTED.

## Incident response for the platform itself

1. **Suspect an agent is misbehaving** (bad comments, unexpected re-runs, cost spike): flip the [kill switch](runbooks/kill-switch.md) for that agent; runs end `denied` immediately.
2. **Suspect credential exposure**: [rotate](runbooks/rotate-credentials.md); grep the ledger for `redactions` kinds to see whether the pattern was caught.
3. **Suspect ledger tampering**: `regent ledger verify`; compare with the copy in the SIEM.
4. **Post-mortem**: the ledger gives the exact prompt ids, skills and mandate in force; reproduce with `REGENT_PROVIDER=replay` fixtures built from the recorded outputs; add an eval case; ship the prompt or mandate change with it.
