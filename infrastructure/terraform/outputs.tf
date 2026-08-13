# ============================================================================
# What the deploy script and the operator need after `terraform apply`.
#
# No secret is emitted as a plain output. Terraform state holds them regardless
# -- which is exactly why terraform.tfstate is gitignored and why the enterprise
# path moves state into a storage account with restricted access.
# ============================================================================

output "resource_group" {
  description = "Resource group holding the whole stack. Deleting it deletes everything."
  value       = module.resource_group.name
}

output "location" {
  value = module.resource_group.location
}

output "api_url" {
  description = "Public HTTPS endpoint of the analytics API. Swagger at /docs."
  value       = module.container_app.api_url
}

output "web_url" {
  description = "Public HTTPS endpoint of the console."
  value       = trimsuffix(module.storage.web_endpoint, "/")
}

output "keycloak_url" {
  description = <<-EOT
    Keycloak. Admin console at /admin, realm at /realms/transferops.
    Scaled to zero: the first request after idle waits 40-60 seconds.
  EOT
  value       = module.container_app.keycloak_url
}

output "keycloak_admin_username" {
  value = var.keycloak_admin_username
}

output "keycloak_admin_password" {
  description = "Retrieve with: terraform output -raw keycloak_admin_password"
  value       = random_password.keycloak_admin.result
  sensitive   = true
}

output "database_fqdn" {
  description = "PostgreSQL host. Reachable from the operator IP if one was supplied."
  value       = module.database.fqdn
}

output "database_name" {
  value = module.database.database_name
}

output "storage_account" {
  value = module.storage.account_name
}

output "key_vault_uri" {
  description = "Empty when enable_key_vault is false."
  value       = module.identity.key_vault_uri
}

output "managed_identity_client_id" {
  description = "Client id the containers present to Azure for blob and vault access."
  value       = module.identity.client_id
}

output "scheduled_job" {
  description = "Container Apps Job running the nightly refresh."
  value       = module.container_app.job_name
}

output "container_registry" {
  description = "ACR login server, or a note that GHCR is in use."
  value       = var.use_acr ? azurerm_container_registry.this[0].login_server : "not provisioned (using ${var.image_registry_server != "" ? var.image_registry_server : "a public registry"})"
}

# ---- Operator credentials --------------------------------------------------
# Marked sensitive, so they are shown only via an explicit
# `terraform output -raw <name>` and never printed by a bare `terraform apply`.

output "postgres_admin_username" {
  value = var.postgres_admin_username
}

output "postgres_admin_password" {
  description = "Retrieve with: terraform output -raw postgres_admin_password"
  value       = random_password.postgres_admin.result
  sensitive   = true
}

output "loader_dsn" {
  description = <<-EOT
    Admin DSN for `python etl/run.py --engine postgres --dsn "$(terraform output -raw loader_dsn)"`.
    Requires allowed_client_ip to have been set, or the firewall will refuse it.
  EOT
  value       = "postgresql://${var.postgres_admin_username}:${urlencode(random_password.postgres_admin.result)}@${module.database.fqdn}:5432/${module.database.database_name}?sslmode=require"
  sensitive   = true
}

output "reader_password" {
  description = "TRANSFEROPS_READER_PASSWORD for the loader, which creates the role."
  value       = random_password.db_reader.result
  sensitive   = true
}

output "auditor_password" {
  value     = random_password.db_auditor.result
  sensitive = true
}

output "ai_password" {
  value     = random_password.db_ai.result
  sensitive = true
}

# ---- A deployment summary worth reading -------------------------------------
output "cost_posture" {
  description = "What this stack bills when idle, so the number is visible at apply time."
  value = join("\n", [
    "Static website        Storage web endpoint  negligible at demo volume",
    "Container Apps (api)  Consumption, min=${var.api_min_replicas}  ${var.api_min_replicas == 0 ? "0.00 when idle (free grant covers demo load)" : "BILLS CONTINUOUSLY - min_replicas > 0"}",
    "Container Apps (auth) Keycloak, min=${var.keycloak_min_replicas}   ${var.keycloak_min_replicas == 0 ? "0.00 when idle; 40-60s cold start on first sign-in" : "BILLS CONTINUOUSLY - roughly 30-35 USD/month, a third of the student credit"}",
    "Container Apps Job    cron, on-demand      ~0.00",
    "PostgreSQL            ${var.postgres_sku_name}   the one standing charge; free for 12 months on an eligible subscription",
    "Blob Storage          Standard_LRS         inside the free grant at demo volume",
    "Log Analytics         capped ${var.log_daily_quota_gb} GB/day   inside the 5 GB/month free grant",
    "Key Vault             ${var.enable_key_vault ? "standard, per-operation ~0.00" : "not provisioned"}",
    "Container Registry    ${var.use_acr ? "ACR Basic - FIXED ~5 USD/month" : "not provisioned (GHCR is free)"}",
  ])
}
