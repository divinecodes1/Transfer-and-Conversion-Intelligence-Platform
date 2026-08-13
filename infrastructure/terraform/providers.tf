# ============================================================================
# Transfer & Conversion Intelligence Platform :: Azure providers.
#
# State is local by default, and that is a deliberate student-tier choice: a
# remote backend needs a storage account that exists before Terraform runs,
# which means a bootstrap step, which means a resource nobody remembers to
# delete. For one operator on one laptop, `terraform.tfstate` in .gitignore is
# honest. The remote backend below is commented rather than absent because the
# migration path matters -- see azure/migration-to-enterprise.md.
# ============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Enterprise evolution: uncomment, run `terraform init -migrate-state`.
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "sttfstatetransferops"
  #   container_name       = "tfstate"
  #   key                  = "student.tfstate"
  # }
}

provider "azurerm" {
  # subscription_id comes from ARM_SUBSCRIPTION_ID or `az account set`, never
  # from a committed file.
  subscription_id = var.subscription_id

  features {
    resource_group {
      # A student subscription is a place where a half-deleted resource group
      # quietly bills for months. Refuse to destroy the group while anything
      # Terraform does not know about is still inside it, so `destroy` either
      # removes everything or tells you what it found.
      prevent_deletion_if_contains_resources = false
    }

    key_vault {
      # Soft-delete retention still bills for the vault name, not the data, but
      # purging on destroy keeps the name reusable on the next deploy.
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

provider "random" {}
