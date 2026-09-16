terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }

  # Remote state with locking. Create the bucket and the table once, by hand or
  # with a tiny bootstrap stack, then uncomment. Never keep state in git.
  #
  # backend "s3" {
  #   bucket         = "acme-terraform-state"
  #   key            = "regent/prod/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "acme-terraform-locks"
  #   encrypt        = true
  #   kms_key_id     = "alias/terraform-state"
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}
