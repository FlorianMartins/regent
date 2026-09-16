output "ecr_repository_url" {
  description = "Where the release workflow pushes the image (in addition to GHCR)."
  value       = aws_ecr_repository.regent.repository_url
}

output "github_deploy_role_arn" {
  description = "Set as the `role-to-assume` of aws-actions/configure-aws-credentials in the workflows."
  value       = aws_iam_role.github_deploy.arn
}

output "ledger_bucket" {
  description = "Write-once archive of the audit ledgers."
  value       = aws_s3_bucket.ledger.id
}

output "llm_secret_arn" {
  description = "Secrets Manager secret holding the LLM credential; set its value out of band."
  value       = aws_secretsmanager_secret.llm.arn
}

output "kms_key_arn" {
  description = "Customer-managed key used by every encrypted resource of the stack."
  value       = aws_kms_key.regent.arn
}

output "log_group" {
  description = "CloudWatch log group for the API."
  value       = aws_cloudwatch_log_group.regent.name
}
