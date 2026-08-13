# ============================================================================
# Transfer & Conversion Intelligence Platform :: student-tier AWS stack.
#
# The shape, and why each piece is what it is:
#
#   console    S3 + CloudFront          static files, no server, free tier
#   API        Lambda + Function URL    scales to zero, 1M requests/month free
#   identity   Keycloak on EC2 t4g.micro   always warm, free on the legacy tier
#   warehouse  RDS PostgreSQL t4g.micro    the one standing charge
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

# ---- Container registry -----------------------------------------------------
# 500 MB is free on the legacy tier and the images are larger than that, so the
# lifecycle policy is not housekeeping -- it is the difference between free and
# a slowly growing charge.

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # a demo registry should never block a teardown

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "keycloak" {
  name                 = "${local.name}-keycloak"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the three most recent images; older ones are rebuildable."
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "keycloak" {
  repository = aws_ecr_repository.keycloak.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the three most recent images."
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}
