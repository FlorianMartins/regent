# Terraform — AWS bootstrap for Regent

What this stack creates, and why each piece exists:

| Resource | Purpose |
|---|---|
| KMS key (`kms.tf`) | One customer-managed key, rotated yearly, for images, the ledger archive, the secret and the logs |
| ECR repository (`ecr.tf`) | Immutable tags (a signed digest cannot be swapped), scan on push, KMS-encrypted |
| GitHub OIDC provider + deploy role (`iam-github-oidc.tf`) | Workflows assume a role with a short-lived token; no access key exists. Trust is limited to this repository, `main` and the release environment |
| Secrets Manager secret (`secrets.tf`) | The container for the LLM key. **The value is never in Terraform** |
| Ledger bucket (`s3-ledger.tf`) | Write-once (Object Lock, COMPLIANCE), versioned, KMS-encrypted, TLS-only, access-logged, archived to Glacier |
| Access-log bucket | Where the ledger bucket's access logs go (a bucket cannot log to itself) |
| CloudWatch log group (`logs.tf`) | Application logs, KMS-encrypted, 90-day retention |

Everything is tagged through `local.common_tags` (project, environment, owner,
cost centre) so FinOps can attribute the bill.

## Bootstrap order

1. **State backend** (once per account): an S3 bucket and a DynamoDB lock table for
   Terraform state. Create them by hand or with a two-resource bootstrap stack, then
   uncomment the `backend "s3"` block in `versions.tf`.
2. `terraform init && terraform plan -out plan.out`
3. Gate the plan: `terraform show -json plan.out | conftest test -p ../../policies/rego --namespace terraform -`
4. `terraform apply plan.out`
5. Set the secret value out of band:
   `aws secretsmanager put-secret-value --secret-id "$(terraform output -raw llm_secret_arn)" --secret-string '<key>'`
6. Copy `github_deploy_role_arn` into the workflows that push to ECR or archive
   ledgers (`aws-actions/configure-aws-credentials` with `role-to-assume`).

## What is deliberately not here

- **The Kubernetes cluster.** Regent runs on whatever cluster the organisation already
  operates (EKS, on-prem, another cloud). `infra/k8s` is cluster-agnostic.
- **Network resources.** No VPC, no security groups: the control plane sits in the
  cluster's network, governed by the NetworkPolicy in `infra/k8s/base`.
- **A local model.** When `max_remote_class` requires a local provider, that model is
  a separate workload (vLLM on GPU nodes); its endpoint goes into `REGENT_LOCAL_URL`.

## Checks

This directory is scanned by CloudGuard-IaC (`make iac-scan`, threshold MEDIUM) and by
the Conftest policy `policies/rego/terraform.rego` on every pull request.
