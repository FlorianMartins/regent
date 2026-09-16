# One customer-managed key for everything the stack encrypts: the ECR images,
# the ledger bucket, the secret and the log group. Rotation is yearly and
# automatic; the key policy is the account default (root + IAM), which is the
# right starting point until a dedicated key-administrator role exists.
resource "aws_kms_key" "regent" {
  description             = "Regent ${var.environment}: images, ledger archive, secrets, logs"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  multi_region            = false
}

resource "aws_kms_alias" "regent" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.regent.key_id
}

# CloudWatch Logs must be allowed to use the key.
data "aws_iam_policy_document" "kms_logs" {
  statement {
    sid    = "AccountAdministration"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = [aws_kms_key.regent.arn]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt*",
      "kms:Decrypt*",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = [aws_kms_key.regent.arn]
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/${local.name}/*"]
    }
  }
}

resource "aws_kms_key_policy" "regent" {
  key_id = aws_kms_key.regent.id
  policy = data.aws_iam_policy_document.kms_logs.json
}
