variable "region" {
  description = "AWS region for every resource in this stack."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Deployment environment: dev, staging or prod."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflows may assume the deploy role through OIDC."
  type        = string
  default     = "FlorianMartins/regent"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

variable "github_environment" {
  description = "GitHub Actions environment name that may assume the deploy role (in addition to pushes to main)."
  type        = string
  default     = "prod"
}

variable "owner" {
  description = "Team or person accountable for the stack (tag)."
  type        = string
  default     = "platform"
}

variable "cost_centre" {
  description = "Cost-centre tag for FinOps allocation."
  type        = string
  default     = "platform-engineering"
}

variable "log_retention_days" {
  description = "Retention of the application log group, in days."
  type        = number
  default     = 90

  validation {
    condition     = var.log_retention_days >= 30
    error_message = "Keep at least 30 days of logs for incident forensics."
  }
}

variable "ledger_retention_days" {
  description = "Days before archived ledger objects move to Glacier. Ledgers are audit evidence: keep them long."
  type        = number
  default     = 365
}
