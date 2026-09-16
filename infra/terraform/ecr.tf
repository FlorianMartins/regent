# The image registry. Tags are immutable so a signed digest can never be swapped
# under a tag; images are scanned on push; the repository is encrypted with our key.
resource "aws_ecr_repository" "regent" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.regent.arn
  }
}

# Keep the last 20 release images; untagged layers go after a week.
resource "aws_ecr_lifecycle_policy" "regent" {
  repository = aws_ecr_repository.regent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "keep the last 20 tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 20
        }
        action = { type = "expire" }
      },
    ]
  })
}
