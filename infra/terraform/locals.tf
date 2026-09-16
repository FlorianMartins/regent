locals {
  name = "regent-${var.environment}"

  # Every resource carries these tags: who owns it, where it runs, who pays.
  common_tags = {
    Project     = "regent"
    Environment = var.environment
    Owner       = var.owner
    CostCentre  = var.cost_centre
    ManagedBy   = "terraform"
    Repository  = "github.com/${var.github_repository}"
  }
}

data "aws_caller_identity" "current" {}
