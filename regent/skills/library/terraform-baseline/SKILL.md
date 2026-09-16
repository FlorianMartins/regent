---
name: terraform-baseline
version: "1"
description: Organisation baseline for Terraform — what a compliant module looks like.
applies_to: [iac-guardian]
checks: [cloudguard_clean_after_fix]
---
Baseline every Terraform change must respect:
- Storage is private by default: `aws_s3_bucket_public_access_block` with all four flags true; encryption with a KMS key (`aws_s3_bucket_server_side_encryption_configuration`); versioning on.
- Security groups never allow `0.0.0.0/0` on administration ports (22, 3389, 5432, 3306, 6379, 27017). Use the corporate CIDR variable `var.corporate_cidrs`.
- IAM policies name resources; `Action = "*"` on `Resource = "*"` is forbidden.
- Every resource carries `tags = local.common_tags` (owner, environment, cost-centre).
- Provider versions are pinned with `~>`; the state backend is remote with locking.
When fixing a finding, keep variable names and module structure; add a variable rather than hard-coding a value you do not know.
