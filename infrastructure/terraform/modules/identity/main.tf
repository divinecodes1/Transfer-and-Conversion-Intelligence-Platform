# User-assigned managed identity and Key Vault.
#
# The identity is user-assigned rather than system-assigned so the same
# principal serves the API container, the scheduled job and any future worker.
# A system-assigned identity dies with its resource, which means every role
# assignment has to be re-granted on replacement -- and one of them will be
# forgotten.
#
# Key Vault is on by default. At demo volume it bills per 10,000 operations and
# rounds to nothing, so this is close to a free upgrade from "secrets in
# environment variables" to "secrets fetched by an identity that can be revoked
# centrally". The Container Apps secret path still exists as a fallback for a
# deployment that wants one fewer moving part -- see enable_key_vault.
#
# RBAC authorisation, not access policies. Access policies are the legacy model
# and cannot be assigned at a scope narrower than the whole vault.

variable "identity_name" { type = string }
variable "key_vault_name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }
variable "enable_key_vault" { type = bool }
variable "storage_account_id" { type = string }
variable "secrets" {
  type      = map(string)
  sensitive = true
}

data "azurerm_client_config" "current" {}

resource "azurerm_user_assigned_identity" "this" {
  name                = var.identity_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

# Blob access by identity. "Storage Blob Data Contributor" is scoped to this one
# account -- the app can write its reports and read its knowledge documents and
# has no standing on any other storage in the subscription.
resource "azurerm_role_assignment" "blob" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

resource "azurerm_key_vault" "this" {
  count = var.enable_key_vault ? 1 : 0

  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  enable_rbac_authorization = true

  # Seven days is the minimum retention. It exists so a fat-fingered destroy is
  # recoverable; it also means the vault name is reserved for a week, which is
  # why providers.tf purges on destroy.
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # blocks `terraform destroy` outright if true

  tags = var.tags
}

# The deploying principal needs to write the secrets it just generated.
resource "azurerm_role_assignment" "deployer_secrets_officer" {
  count = var.enable_key_vault ? 1 : 0

  scope                = azurerm_key_vault.this[0].id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# The application reads, and only reads.
resource "azurerm_role_assignment" "app_secrets_user" {
  count = var.enable_key_vault ? 1 : 0

  scope                = azurerm_key_vault.this[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

resource "azurerm_key_vault_secret" "secrets" {
  # An empty value is a real state -- ai-api-key is blank in mock mode -- and
  # Key Vault rejects empty secrets, so those are skipped rather than faked.
  for_each = var.enable_key_vault ? {
    for k, v in var.secrets : k => v if v != ""
  } : {}

  name         = each.key
  value        = each.value
  key_vault_id = azurerm_key_vault.this[0].id

  depends_on = [azurerm_role_assignment.deployer_secrets_officer]
}

output "identity_id" { value = azurerm_user_assigned_identity.this.id }
output "principal_id" { value = azurerm_user_assigned_identity.this.principal_id }
output "client_id" { value = azurerm_user_assigned_identity.this.client_id }
output "key_vault_uri" {
  value = var.enable_key_vault ? azurerm_key_vault.this[0].vault_uri : ""
}
output "key_vault_id" {
  value = var.enable_key_vault ? azurerm_key_vault.this[0].id : ""
}
