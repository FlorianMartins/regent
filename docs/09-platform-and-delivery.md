# Platform and delivery

!!! tip "In plain words"
    This page is about the machine room: where Regent runs, how a new version gets there safely, how it is protected, and how it is put back if something breaks. The principle is *GitOps*: the desired state of the cluster is a folder in Git, a robot (Argo CD) makes the cluster match it, and a change to production is a reviewed pull request like any other.

## Environments

| Environment | Purpose | Mandates | Model provider |
|---|---|---|---|
| `dev` | Developers and CI; disposable | Defaults; `dry_run` common | `replay` in CI, `anthropic` with a dev key locally |
| `staging` | Same manifests as prod, fed by a mirror of webhooks | Same files as prod, `kill_switch` per agent until validated | Anthropic + local model |
| `prod` | Live | Reviewed overrides per repository | Anthropic; local model mandatory for RESTRICTED |

The environment name reaches the runtime as the `--env` / `environment` field and drives mandate resolution (`environments:` globs).

## Repository layout of the infrastructure

```text
infra/
  compose/      local stack: regent-api, Prometheus, Grafana (dashboards), OTel collector
  k8s/          Kustomize base + overlays (dev, staging, prod); Argo CD Application(s); Argo Rollouts
  terraform/    cloud foundations (state, OIDC role for CI, registry, KMS, secrets)
policies/
  mandates/     agent mandates (YAML)
  rego/         OPA policies for Kubernetes manifests and Terraform plans (Conftest in CI)
```

The infrastructure code is scanned by CloudGuard-IaC and Conftest in the pipeline: the platform passes the gate it enforces.

## Kubernetes baseline

The `regent-api` workload (Kustomize base) follows the same `kubernetes-baseline` skill the agents apply to others: non-root user, all capabilities dropped, read-only root filesystem, CPU/memory requests and limits, image pinned by digest, readiness (`/readyz`) and liveness (`/healthz`) probes, a ServiceAccount with no token automount, a NetworkPolicy (ingress from the ingress controller only; egress to GitHub, the LLM provider, the local model service, Prometheus, the OTel collector), a PodDisruptionBudget and a HorizontalPodAutoscaler. Secrets are projected from External Secrets Operator, never in manifests.

## GitOps with Argo CD

- An *app-of-apps* Application points at `infra/k8s`; one child Application per overlay.
- Sync policy: automated with self-heal in dev; manual sync approval in prod.
- Drift (someone `kubectl edit`s prod) is reported and reverted; the ledger of infrastructure is Git.

## Progressive delivery

Argo Rollouts drives a canary: 10 % → 50 % → 100 % with analysis steps on `regent_runs_total{status="failed"}` rate, `regent_run_duration_seconds` p95 and `regent_verifications_total{verdict="rejected"}` rate. A regression in the verifier rejection rate — the platform's own quality signal — aborts the rollout automatically.

## Terraform layout and state

`infra/terraform` provides the cloud foundations: an S3 state bucket with versioning, KMS encryption and a DynamoDB lock table; an IAM role assumable through **GitHub OIDC** (no long-lived keys in CI); an ECR repository with immutable tags and scan-on-push; a KMS key; Secrets Manager entries for the API key and webhook secrets. Provider versions are pinned with `~>`; `terraform fmt`/`validate` and CloudGuard run in CI; Conftest checks the plan (no public buckets, no `0.0.0.0/0` on admin ports, tags present).

## Secrets

External Secrets Operator syncs Secrets Manager / Vault entries into namespaced Kubernetes Secrets; the deployment reads them as environment variables (`ANTHROPIC_API_KEY`, `GITHUB_WEBHOOK_SECRET`, `ALERTMANAGER_WEBHOOK_TOKEN`, the GitHub App private key for token minting). Rotation is a change in the secret manager; pods restart via the operator's refresh. [Runbook](runbooks/rotate-credentials.md).

## Backup and disaster recovery

| Data | Backup | Restore |
|---|---|---|
| Ledger | Streamed to the SIEM / object storage with object lock; pod-local file is a buffer | Re-verify the chain on the restored copy |
| Run store | In memory today ([ADR-0009](adr/ADR-0009-run-store.md)); in production Postgres with point-in-time recovery | Standard PITR; runs are also reconstructible from the ledger |
| Mandates, prompts, skills, evals | Git | Git |
| Infrastructure | Git + Terraform state (versioned bucket) | `terraform apply`; Argo CD re-syncs the cluster |

RPO for the ledger is the shipping interval (seconds); RTO for the control plane is a re-sync of the Argo application. A lost control plane loses no audit data that had been shipped and no configuration at all.

## Scaling

The API is stateless apart from the in-memory run store; runs are CPU-light and I/O-bound (waiting on the model and GitHub). HPA on CPU and on `regent_runs_in_flight`. The ceiling is the provider's rate limit; the SDK retries with backoff (max 3) and a rate-limit error becomes a `failed` run, never a hang.

## Upgrade strategy

1. Bump the version (`regent/__init__.py`), tag; the release workflow builds, scans, attests and signs the image.
2. Argo CD picks up the new digest in the overlay (a PR).
3. Canary as above; rollback is `kubectl argo rollouts undo` or reverting the overlay PR.
4. Prompt and skill changes ride the same release; the ledger shows the new ids from the first run.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make check                      # lint, types, tests, SAST, policy-check, evals — the CI gates
docker compose -f infra/compose/docker-compose.yml up   # API + Prometheus + Grafana + OTel collector
REGENT_PROVIDER=replay regent run pr-reviewer --repo acme/example --payload '{"number": 42}' --dry-run
```

`make` targets mirror the CI jobs so that a green `make check` is a green pipeline.
