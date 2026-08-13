# Blob storage for documents, generated reports and exports.
#
# Standard_LRS, hot tier, no redundancy beyond the local replicas LRS already
# gives. GRS doubles the price to survive a regional outage, which is not a
# risk a demo needs to price in.
#
# The lifecycle policy is the part that matters for cost control: exports and
# reports are regenerable, so they expire on their own. Storage that only ever
# grows is the classic way a "free" 5 GB grant becomes a charge in month four.

variable "account_name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_storage_account" "this" {
  name                     = var.account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  # Access is by managed identity and RBAC, never by account key. Disabling the
  # shared key removes the credential that would otherwise need rotating -- and
  # removes the one most likely to end up pasted into a .env.
  shared_access_key_enabled = false

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  tags = var.tags
}

# The Vite console is a static SPA. Hosting it on the storage web endpoint keeps
# the student deployment inside regions permitted by Azure subscription policy
# and avoids another standing service. Sending 404s to index.html preserves
# client-side routing for direct links such as /distribution.
resource "azurerm_storage_account_static_website" "web" {
  storage_account_id = azurerm_storage_account.this.id
  index_document     = "index.html"
  error_404_document = "index.html"
}

resource "azurerm_storage_container" "containers" {
  for_each = toset([
    "transfer-documents",
    "reports",
    "knowledge",
    "exports",
  ])

  name                  = each.value
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "lifecycle" {
  storage_account_id = azurerm_storage_account.this.id

  # Exports are a user pressing "download". They are reproducible from the
  # warehouse in seconds and there is no reason to pay to keep them.
  rule {
    name    = "expire-exports"
    enabled = true
    filters {
      prefix_match = ["exports/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 7
      }
    }
  }

  # Generated management reports last a month -- long enough to show a weekly
  # reporting cycle, short enough not to accumulate.
  rule {
    name    = "expire-generated-reports"
    enabled = true
    filters {
      prefix_match = ["reports/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 30
      }
    }
  }

  # Knowledge documents feed the retrieval index and are inputs, not outputs.
  # They are never auto-deleted; they cool instead, which is cheaper per GB.
  rule {
    name    = "cool-knowledge"
    enabled = true
    filters {
      prefix_match = ["knowledge/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 30
      }
    }
  }
}

output "account_id" { value = azurerm_storage_account.this.id }
output "account_name" { value = azurerm_storage_account.this.name }
output "blob_endpoint" { value = azurerm_storage_account.this.primary_blob_endpoint }
output "web_endpoint" { value = azurerm_storage_account.this.primary_web_endpoint }
