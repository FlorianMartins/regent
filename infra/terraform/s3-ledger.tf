# The audit ledger archive. Every property of this bucket exists for one reason:
# the ledger is evidence, and evidence must be complete, private and immutable.
#   * public access blocked four ways   — private, whatever a future policy says
#   * versioning + Object Lock          — an archived ledger cannot be overwritten or deleted
#   * SSE-KMS with our key              — readable only by principals we allow on the key
#   * access logging                    — who read the evidence is itself evidence
#   * lifecycle to Glacier              — cheap to keep for years
resource "aws_s3_bucket" "ledger" {
  bucket              = "${local.name}-ledger-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "ledger" {
  bucket                  = aws_s3_bucket.ledger.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ledger" {
  bucket = aws_s3_bucket.ledger.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "ledger" {
  bucket = aws_s3_bucket.ledger.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.ledger_retention_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.ledger]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ledger" {
  bucket = aws_s3_bucket.ledger.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.regent.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "ledger" {
  bucket        = aws_s3_bucket.ledger.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "ledger/"
}

resource "aws_s3_bucket_lifecycle_configuration" "ledger" {
  bucket = aws_s3_bucket.ledger.id
  rule {
    id     = "archive"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER_IR"
    }
  }
  depends_on = [aws_s3_bucket_versioning.ledger]
}

# TLS only: a request over plain HTTP is denied even with valid credentials.
data "aws_iam_policy_document" "ledger_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.ledger.arn, "${aws_s3_bucket.ledger.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "ledger" {
  bucket = aws_s3_bucket.ledger.id
  policy = data.aws_iam_policy_document.ledger_tls_only.json
}

# ---- access-log bucket -------------------------------------------------------
# The log destination cannot log to itself (S3 refuses the loop), which is why
# CG_IAC_015 is suppressed on this one bucket with a stated reason.

# cloudguard:ignore CG_IAC_015 access-log destination bucket; S3 refuses a bucket that logs to itself
resource "aws_s3_bucket" "access_logs" {
  bucket = "${local.name}-access-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.regent.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

# The S3 logging service principal must be allowed to write here.
data "aws_iam_policy_document" "access_logs" {
  statement {
    sid    = "S3ServerAccessLogsPolicy"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs.json
}
