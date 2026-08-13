# ============================================================================
# Transfer & Conversion Intelligence Platform :: student-tier Azure stack.
#
# Nine resources, one region, one resource group. Every one of them either
# scales to zero, sits inside a free monthly grant, or is the smallest SKU its
# service offers. The architecture is the enterprise shape -- identity-based
# access to storage and secrets, a governed database behind a least-privilege
# role, structured telemetry -- built on the tier that costs nothing when idle.
#
# What is deliberately NOT here: AKS, Front Door, Application Gateway, Firewall,
# Redis, private endpoints, a vector database, an Airflow cluster, a second
# region. Each is a real production component and each is a standing charge; see
# azure/migration-to-enterprise.md for where they slot in when someone else is
# paying.
# ============================================================================

locals {
  name_prefix = "${var.prefix}-%s-${var.environment}"

  # Globally-unique names have no hyphens and a short random suffix, because
  # "tistudent" is almost certainly taken and the failure arrives late.
  unique_suffix = random_string.suffix.result

  tags = {
    project     = "transfer-intelligence"
    environment = var.environment
    owner       = var.owner
    purpose     = "demo"
    cost-center = "education"
    managed-by  = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 5
  special = false
  upper   = false
}

resource "random_password" "postgres_admin" {
  length           = 32
  special          = true
  override_special = "!#$%*()-_=+[]{}<>:?"
}

# The application's least-privilege database roles. The loader creates the roles
# with these passwords; the API never connects as the admin.
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

# ---- Resource group and budget ---------------------------------------------
module "resource_group" {
  source = "./modules/resource-group"

  name                  = "rg-transfer-intelligence-${var.environment}"
  location              = coalesce(var.resource_group_location, var.location)
  tags                  = local.tags
  budget_amount         = var.monthly_budget_amount
  budget_time_grain     = var.budget_time_grain
  budget_contact_emails = var.budget_alert_emails
}

# ---- Observability ---------------------------------------------------------
module "monitoring" {
  source = "./modules/monitoring"

  workspace_name      = format(local.name_prefix, "logs")
  app_insights_name   = format(local.name_prefix, "monitor")
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags
  retention_in_days   = var.log_retention_days
  daily_quota_gb      = var.log_daily_quota_gb
}

# ---- Blob storage ----------------------------------------------------------
module "storage" {
  source = "./modules/storage"

  account_name        = "${var.prefix}stor${var.environment}${local.unique_suffix}"
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags
}

# ---- PostgreSQL ------------------------------------------------------------
module "database" {
  source = "./modules/database"

  server_name            = format(local.name_prefix, "db")
  resource_group_name    = module.resource_group.name
  location               = var.location
  tags                   = local.tags
  sku_name               = var.postgres_sku_name
  storage_mb             = var.postgres_storage_mb
  backup_retention_days  = var.postgres_backup_retention_days
  administrator_login    = var.postgres_admin_username
  administrator_password = random_password.postgres_admin.result
  allowed_client_ip      = var.allowed_client_ip
}

# ---- Managed identity and Key Vault ----------------------------------------
module "identity" {
  source = "./modules/identity"

  identity_name       = format(local.name_prefix, "id")
  key_vault_name      = "${var.prefix}kv${var.environment}${local.unique_suffix}"
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags
  enable_key_vault    = var.enable_key_vault
  storage_account_id  = module.storage.account_id

  secrets = var.enable_key_vault ? merge({
    "postgres-admin-password" = random_password.postgres_admin.result
    "db-reader-password"      = random_password.db_reader.result
    "db-auditor-password"     = random_password.db_auditor.result
    "db-ai-password"          = random_password.db_ai.result
    "keycloak-admin-password" = random_password.keycloak_admin.result
    }, var.ai_api_key != "" ? {
    "ai-api-key" = var.ai_api_key
  } : {}) : {}
}

# ---- Container registry (optional; off by default) -------------------------
# ACR Basic is a fixed monthly charge regardless of use. GitHub Container
# Registry serves public images for free and is the default path.
resource "azurerm_container_registry" "this" {
  count = var.use_acr ? 1 : 0

  name                = "${var.prefix}acr${var.environment}${local.unique_suffix}"
  resource_group_name = module.resource_group.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  count = var.use_acr ? 1 : 0

  scope                = azurerm_container_registry.this[0].id
  role_definition_name = "AcrPull"
  principal_id         = module.identity.principal_id
}

# ---- Compute ---------------------------------------------------------------
module "container_app" {
  source = "./modules/container-app"

  environment_name    = format(local.name_prefix, "cae")
  api_app_name        = format(local.name_prefix, "api")
  job_name            = format(local.name_prefix, "etl")
  static_site_name    = format(local.name_prefix, "web")
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags

  log_analytics_workspace_id = module.monitoring.workspace_id
  identity_id                = module.identity.identity_id
  identity_client_id         = module.identity.client_id

  image                  = var.api_image
  registry_server        = var.use_acr ? azurerm_container_registry.this[0].login_server : var.image_registry_server
  registry_username      = var.image_registry_username
  registry_password      = var.image_registry_password
  registry_uses_identity = var.use_acr

  min_replicas = var.api_min_replicas
  max_replicas = var.api_max_replicas
  cpu          = var.api_cpu
  memory       = var.api_memory

  # Secrets travel as Container Apps secrets, which are referenced by name in
  # the env block and never appear in `terraform output` or a container's
  # inspect payload.
  secrets = {
    "db-admin-password"   = random_password.postgres_admin.result
    "db-reader-password"  = random_password.db_reader.result
    "db-auditor-password" = random_password.db_auditor.result
    "db-ai-password"      = random_password.db_ai.result
    "ai-api-key"          = var.ai_api_key
  }

  env = {
    APP_ENV                               = var.environment
    TRANSFEROPS_AUTH                      = var.auth_mode
    TRANSFEROPS_LOG_FORMAT                = "json"
    TRANSFEROPS_LOG_LEVEL                 = "INFO"
    TRANSFEROPS_AI_PROVIDER               = var.ai_provider
    TRANSFEROPS_AI_MODEL                  = var.ai_model
    TRANSFEROPS_AI_BASE_URL               = var.ai_base_url
    TRANSFEROPS_AI_DAILY_CAP              = tostring(var.ai_daily_request_cap)
    AZURE_STORAGE_ACCOUNT                 = module.storage.account_name
    AZURE_CLIENT_ID                       = module.identity.client_id
    APPLICATIONINSIGHTS_CONNECTION_STRING = module.monitoring.connection_string
  }

  # Passwords reach the containers as secrets and are woven into DSNs inside the
  # module, so no connection string appears in a plain environment variable.
  db_host  = module.database.fqdn
  db_name  = module.database.database_name
  db_admin = var.postgres_admin_username

  # Identity provider. Keycloak runs as its own Container App on the same
  # environment, with its own database on the shared server.
  keycloak_app_name       = format(local.name_prefix, "auth")
  keycloak_image          = var.keycloak_image
  keycloak_database_name  = module.database.keycloak_database_name
  keycloak_admin_username = var.keycloak_admin_username
  keycloak_admin_password = random_password.keycloak_admin.result
  keycloak_realm          = var.keycloak_realm
  keycloak_audience       = var.keycloak_audience
  keycloak_min_replicas   = var.keycloak_min_replicas
  keycloak_cpu            = var.keycloak_cpu
  keycloak_memory         = var.keycloak_memory

  # Supplied so realm import can resolve the placeholders in the smtpServer
  # block. Empty host means no mail is sent -- see the note in the module.
  keycloak_smtp = {
    KEYCLOAK_SMTP_HOST     = var.keycloak_smtp_host
    KEYCLOAK_SMTP_PORT     = var.keycloak_smtp_port
    KEYCLOAK_SMTP_FROM     = var.keycloak_smtp_from
    KEYCLOAK_SMTP_REPLY_TO = var.keycloak_smtp_from
    KEYCLOAK_SMTP_USER     = var.keycloak_smtp_user
    KEYCLOAK_SMTP_PASSWORD = var.keycloak_smtp_password
    KEYCLOAK_SMTP_AUTH     = var.keycloak_smtp_user == "" ? "false" : "true"
    KEYCLOAK_SMTP_SSL      = "false"
    KEYCLOAK_SMTP_STARTTLS = var.keycloak_smtp_host == "" ? "false" : "true"
  }
}
