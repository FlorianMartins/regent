# A deliberately vulnerable module: the IaC guardian's demo corpus.
# CloudGuard-IaC flags the public ACL, the missing encryption/versioning and
# the security group open to the world on SSH.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-3"
}

resource "aws_s3_bucket" "uploads" {
  bucket = "acme-demo-uploads"
  acl    = "public-read"
}

resource "aws_security_group" "bastion" {
  name        = "bastion"
  description = "SSH from anywhere"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
