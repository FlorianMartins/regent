# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (main) | ✅ |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem in Regent itself.

Use GitHub's private reporting — *Security* → *Report a vulnerability* on
<https://github.com/FlorianMartins/regent/security/advisories/new> — and include:

- the affected version, the provider in use (`anthropic`, `local`, `replay`) and the
  deployment shape (CLI in CI, API server, Kubernetes),
- a minimal reproducer — a mandate file, a trigger payload and, if relevant, the
  ledger excerpt of the run (`regent ledger show --run <id>`; redact repository data),
- the impact you see.

Expect an acknowledgement within 72 hours and an assessment within seven days. Fixes ship
in a patch release, credited in [CHANGELOG.md](CHANGELOG.md) unless you prefer otherwise.

## What Regent is, from a security point of view

Regent lets language-model agents read repositories, logs and alerts and — under a
mandate — write comments, open pull requests, re-run jobs or merge routine changes.
The full threat model lives in [`docs/06-security.md`](docs/06-security.md); the
properties the platform promises are:

- **Nothing runs without a mandate.** An agent, a repository and an environment with
  no matching mandate produce a `denied` run and no side effect.
- **Tools are allow-listed, never deny-listed.** A tool absent from the mandate is
  refused, whatever the model asks for.
- **`L4_ACT` (irreversible actions) is never granted.** `regent policy-check` and the
  Conftest policy in `policies/rego/mandates.rego` both refuse a mandate that tries.
- **Analysis is read-only.** Tools above `READ` are blocked until the output has been
  verified by deterministic checks and an independent critic.
- **Credentials never reach a model.** Every prompt and tool result passes through the
  redaction layer; a recognised secret is replaced before the request leaves.
- **Confidential data stays where the mandate says.** Content classified above the
  mandate's `max_remote_class` is refused for remote providers, or routed to a local one.
- **Every decision is on the record.** The ledger is hash-chained; `regent ledger verify`
  detects any edit, removal or reordering.
- **Agents never get a shell.** Command execution is an allow-list of fixed argv prefixes
  with validated arguments, a timeout, a scrubbed environment and the run's workspace
  as the working directory.

### In scope

- A way for content the agent reads (a diff, a log, a PR body, an alert) to make an
  agent call a tool its mandate does not allow, or to reach a higher autonomy level.
- A way to send a credential or `RESTRICTED` content to a remote provider despite the
  redaction and classification layers.
- A ledger tampering that `regent ledger verify` does not detect.
- A path escape in the workspace tools, or an argument that reaches a shell through the
  sandbox allow-list.
- Webhook signature or token bypass on the control-plane API.

### Out of scope

- A model producing a wrong review, a wrong hypothesis or a missed finding. Verification
  and mandates bound the damage; they do not make the model right. Open a normal issue
  with the eval case that would have caught it.
- Vulnerabilities in the language-model provider, in GitHub, or in third-party actions
  the pipeline uses — report them upstream.
- Misconfiguration of a deployment that widens a mandate on purpose.

## Operational hygiene expected from deployers

- Run the API behind an identity-aware proxy or a private ingress; the API itself only
  authenticates webhooks.
- Give the agent identity (a GitHub App or the job token) the minimum permissions its
  mandates need — `pull-requests: write` for the reviewer, nothing for read-only runs.
- Ship the ledger to write-once storage (the Terraform module creates an S3 bucket with
  versioning for that purpose) and alert on `regent ledger verify` failures.
- Rotate the LLM key through the secret manager; never bake it into an image or a
  mandate file.

## Reports and ledgers contain sensitive material

A ledger names repositories, files and findings; an eval report may embed diffs. Treat
both as internal artefacts: private artefact storage, retention limits, no public bucket.
