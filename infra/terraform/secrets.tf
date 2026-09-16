# The LLM credential lives in Secrets Manager. Terraform creates the *container*;
# the value is set out of band (console, CLI, or the External Secrets Operator's
# push mechanism) so it never touches state or git.
resource "aws_secretsmanager_secret" "llm" {
  name                    = "${local.name}/llm"
  description             = "Regent ${var.environment}: LLM provider credential (value set out of band)"
  kms_key_id              = aws_kms_key.regent.arn
  recovery_window_in_days = 30
}

# Grant the workload identity (IRSA role of the Kubernetes service account)
# read access here once the cluster exists:
#
# data "aws_iam_policy_document" "secret_read" {
#   statement {
#     effect    = "Allow"
#     actions   = ["secretsmanager:GetSecretValue"]
#     resources = [aws_secretsmanager_secret.llm.arn]
#   }
# }
