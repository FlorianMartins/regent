# Application logs from the cluster (via Fluent Bit or the CloudWatch agent).
resource "aws_cloudwatch_log_group" "regent" {
  name              = "/${local.name}/api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.regent.arn

  depends_on = [aws_kms_key_policy.regent]
}
