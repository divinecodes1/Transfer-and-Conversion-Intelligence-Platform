# ============================================================================
# Transfer & Conversion Intelligence Platform :: AWS providers.
#
# Flat files rather than modules. The Azure stack used modules because six
# resource groups of concern each had real internal wiring; this one is a single
# environment of about thirty resources, and a module per file would add a
# variables/outputs round-trip to every value without hiding any complexity. The
# files are the boundaries: network.tf, database.tf, api.tf, keycloak.tf,
# site.tf, secrets.tf, github_oidc.tf, budget.tf.
#
# State is local and gitignored, which is a deliberate student-tier choice: an
# S3 backend needs a bucket that exists before Terraform runs, and that bootstrap
# resource is the one nobody remembers to delete.
# ============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Enterprise evolution: uncomment, run `terraform init -migrate-state`.
  # backend "s3" {
  #   bucket       = "transferops-tfstate"
  #   key          = "student/terraform.tfstate"
  #   region       = "eu-central-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = "transfer-intelligence"
      environment = var.environment
      owner       = var.owner
      purpose     = "demo"
      cost-center = "education"
      managed-by  = "terraform"
    }
  }
}

# CloudFront only accepts ACM certificates from us-east-1, and the WAF/edge
# resources are global. Declared even though the student tier uses the default
# CloudFront certificate, so adding a custom domain later is a variable change
# rather than a provider refactor.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      project     = "transfer-intelligence"
      environment = var.environment
      managed-by  = "terraform"
    }
  }
}

provider "random" {}
provider "tls" {}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
