# ============================================================================
# Transfer & Conversion Intelligence Platform :: student-tier AWS stack.
#
# The shape, and why each piece is what it is:
#
#   console    S3 + CloudFront          static files, no server process
#   API/agent  three Lambda functions   API, assistant and nightly refresh
#   identity   CloudFront -> Keycloak   HTTPS without a domain
#   warehouse  private RDS PostgreSQL   no public ingress
#   pipeline   EventBridge -> Lambda       runs for seconds, once a night
#   secrets    SSM Parameter Store      free, where Secrets Manager is 0.40/secret
#   CI         GitHub OIDC -> IAM role  no stored credential, no directory admin
#
# What is deliberately absent: NAT gateway, ALB, ECS, EKS, Aurora, ElastiCache,
# Secrets Manager, WAF, a second region. Each is a real production component and
# each is a standing charge measured in tens of dollars a month.
# ============================================================================

locals {
  name = "${var.prefix}-${var.environment}"

  # S3 bucket names are globally unique; a suffix avoids the near-certain clash.
  bucket_name = "${var.prefix}-console-${var.environment}-${random_string.suffix.result}"
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# ---- Generated credentials --------------------------------------------------
# Written to SSM, never to a file, never to a plain environment variable.

resource "random_password" "db_master" {
  length = 32
  # RDS rejects '/', '@', '"' and space in a master password, and a DSN would
  # need the rest percent-encoded anyway.
  special          = true
  override_special = "!#$%^&*()-_=+[]{}<>:?"
}

resource "random_password" "db_reader" {
  length  = 24
  special = false
}

resource "random_password" "db_auditor" {
  length  = 24
  special = false
}

resource "random_password" "db_ai" {
  length  = 24
  special = false
}

resource "random_password" "keycloak_admin" {
  length  = 28
  special = false
}

check "smtp_configuration" {
  assert {
    condition = var.smtp_host == "" || (
      var.smtp_from != "" && (!var.smtp_auth || (var.smtp_username != "" && var.smtp_password != ""))
    )
    error_message = "SMTP requires smtp_from; authenticated SMTP also requires smtp_username and smtp_password."
  }
}

# ECR is deliberately owned by infrastructure/aws/bootstrap. The repositories
# must exist before the first application apply because Lambda validates that
# its image URI exists while creating the function.
data "aws_ecr_repository" "api" {
  name = "${local.name}-api"
}

data "aws_ecr_repository" "keycloak" {
  name = "${local.name}-keycloak"
}
