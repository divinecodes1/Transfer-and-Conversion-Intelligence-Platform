# ============================================================================
# Transfer & Conversion Intelligence Platform :: student-tier inputs.
#
# Every default here is the cheapest option that still demonstrates the
# architecture. Where a default costs money, the comment says how much and what
# the free alternative is -- a variable whose price is invisible is a variable
# that gets raised "just to be safe" and discovered on the invoice.
# ============================================================================

variable "subscription_id" {
  description = "Azure subscription id. Supply via ARM_SUBSCRIPTION_ID, not a committed tfvars."
  type        = string
}

variable "prefix" {
  description = "Short resource-name prefix. Names become ti-<resource>-<environment>."
  type        = string
  default     = "ti"

  validation {
    # Storage accounts and ACR names are globally unique, lower-case and
    # alphanumeric-only. Catching that here beats a failure 90 seconds into apply.
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.prefix))
    error_message = "prefix must be 2-8 lower-case alphanumeric characters starting with a letter."
  }
}

variable "environment" {
  description = "Environment suffix. 'student' for the demo tier."
  type        = string
  default     = "student"
}

variable "location" {
  description = <<-EOT
    Azure region. Keep every resource in one region: cross-region traffic is
    billed, same-region traffic between these services is not. Verify the region
    offers Container Apps and PostgreSQL Flexible Server on your subscription.
  EOT
  type        = string
  default     = "westeurope"
}

variable "owner" {
  description = "Tag value identifying who owns the demo stack."
  type        = string
  default     = "student"
}

# ---- Budget ----------------------------------------------------------------

variable "monthly_budget_amount" {
  description = <<-EOT
    Monthly budget in the subscription's billing currency. This does NOT cap
    spend -- Azure has no hard stop on a credit subscription. It raises alerts,
    and the alerts are the only early warning before the credit is gone.
  EOT
  type        = number
  default     = 10
}

variable "budget_alert_emails" {
  description = "Addresses that receive budget alerts. Empty disables the budget."
  type        = list(string)
  default     = []
}

# ---- Database --------------------------------------------------------------

variable "postgres_sku_name" {
  description = <<-EOT
    PostgreSQL Flexible Server SKU. B_Standard_B1ms is the smallest burstable
    tier and is what the Azure free-services offer covers for 12 months on an
    eligible subscription. Anything larger is a production decision: B2s is
    roughly four times the price for a 260-project warehouse that fits in RAM.
  EOT
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = <<-EOT
    Storage in MB. 32768 is the floor and matches the free-offer allowance.
    Storage cannot be shrunk after creation on Flexible Server -- growing is a
    one-way door, so start at the floor.
  EOT
  type        = number
  default     = 32768
}

variable "postgres_backup_retention_days" {
  description = "Backup retention. 7 is the minimum; retained backups are billed beyond the free allowance."
  type        = number
  default     = 7
}

variable "postgres_admin_username" {
  description = "Server admin login. Not the application's identity -- the app uses the least-privilege reader role."
  type        = string
  default     = "transferops_admin"
}

variable "allowed_client_ip" {
  description = <<-EOT
    Your public IP, so the loader and psql can reach the database. Empty means
    no client rule is created and only Azure services can connect, which is the
    safer default but blocks `etl/run.py` from your laptop.
  EOT
  type        = string
  default     = ""
}

# ---- Container images ------------------------------------------------------

variable "use_acr" {
  description = <<-EOT
    Provision an Azure Container Registry.

    Default false, and this is the single largest cost decision in the file.
    ACR Basic is a FIXED ~5 USD/month whether or not you push anything -- on a
    100 USD credit that is 5% of the budget per month for a service GitHub
    Container Registry provides free for public images. Set true only if the
    images must stay private inside Azure.
  EOT
  type        = bool
  default     = false
}

variable "api_image" {
  description = <<-EOT
    Fully-qualified image for the API container. Defaults to a public GHCR
    reference; the deploy script rewrites it to your repository. When use_acr is
    true this must point at the ACR login server.
  EOT
  type        = string
  default     = "ghcr.io/OWNER/transfer-intelligence:latest"
}

variable "image_registry_server" {
  description = "Registry host for private pulls. Empty means the image is public and no credential is attached."
  type        = string
  default     = ""
}

variable "image_registry_username" {
  description = "Registry username for private pulls. Leave empty for public images."
  type        = string
  default     = ""
  sensitive   = true
}

variable "image_registry_password" {
  description = "Registry password/token for private pulls. Supply via TF_VAR_image_registry_password."
  type        = string
  default     = ""
  sensitive   = true
}

# ---- Container App sizing --------------------------------------------------

variable "api_min_replicas" {
  description = <<-EOT
    Minimum replicas. ZERO is the point of this deployment: an idle demo bills
    nothing. The cost is a cold start of a few seconds on the first request
    after idle, which is the correct trade for a portfolio piece nobody is
    hitting at 3am. Set 1 only while demonstrating live.
  EOT
  type        = number
  default     = 0
}

variable "api_max_replicas" {
  description = "Maximum replicas. Two is enough to show horizontal scaling without a runaway bill."
  type        = number
  default     = 2
}

variable "api_cpu" {
  description = "vCPU per replica. 0.25 with 0.5Gi is the smallest valid Consumption combination."
  type        = number
  default     = 0.25
}

variable "api_memory" {
  description = "Memory per replica. Container Apps requires a fixed 2:1 GiB-to-vCPU ratio."
  type        = string
  default     = "0.5Gi"
}

# ---- Observability ---------------------------------------------------------

variable "log_retention_days" {
  description = "Log Analytics retention. 30 is the minimum billable-free period."
  type        = number
  default     = 30
}

variable "log_daily_quota_gb" {
  description = <<-EOT
    Hard daily ingestion cap in GB. This is a real cap: Log Analytics stops
    ingesting for the day when it is hit, so a logging loop cannot quietly eat
    the credit overnight. 0.1 GB/day stays inside the 5 GB/month free grant with
    room to spare.
  EOT
  type        = number
  default     = 0.1
}

# ---- Application configuration ---------------------------------------------

variable "auth_mode" {
  description = <<-EOT
    TRANSFEROPS_AUTH. 'enforce' requires a verified OIDC token and is the
    platform default. 'demo' accepts an unauthenticated X-Demo-User header and
    must never be used on a public URL.
  EOT
  type        = string
  default     = "enforce"

  validation {
    condition     = contains(["enforce", "demo"], var.auth_mode)
    error_message = "auth_mode must be 'enforce' or 'demo'."
  }
}

variable "ai_provider" {
  description = <<-EOT
    TRANSFEROPS_AI_PROVIDER: anthropic | openai | mock.

    'mock' is the default for a reason: model credits are not guaranteed, and a
    demo that dies because an API key expired is a demo that cannot be shown.
    Mock returns deterministic narratives computed from the governed data.
  EOT
  type        = string
  default     = "mock"

  validation {
    condition     = contains(["anthropic", "openai", "mock"], var.ai_provider)
    error_message = "ai_provider must be one of: anthropic, openai, mock."
  }
}

variable "ai_api_key" {
  description = "Model API key. Supply via TF_VAR_ai_api_key; stored as a Container Apps secret, never in state output."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ai_model" {
  description = "Model id. Left empty the gateway picks its provider default."
  type        = string
  default     = ""
}

variable "ai_base_url" {
  description = "OpenAI-compatible base URL. Point this at an Azure OpenAI deployment to use it without a separate adapter."
  type        = string
  default     = ""
}

variable "ai_daily_request_cap" {
  description = "Per-user daily model-call ceiling enforced in the application, not by the provider."
  type        = number
  default     = 50
}

# ---- Identity --------------------------------------------------------------

variable "keycloak_image" {
  description = <<-EOT
    Keycloak image. Pinned by digest-able tag rather than :latest, so a redeploy
    cannot silently move the identity provider to a new major version.
  EOT
  type        = string
  default     = "quay.io/keycloak/keycloak:26.0"
}

variable "keycloak_admin_username" {
  description = "Bootstrap admin for the Keycloak console. Not an application user."
  type        = string
  default     = "kcadmin"
}

variable "keycloak_realm" {
  description = "Realm name. Must match keycloak/realm-export.json."
  type        = string
  default     = "transferops"
}

variable "keycloak_audience" {
  description = "Expected 'aud' claim. Must match the realm's audience mapper."
  type        = string
  default     = "transferops-api"
}

variable "keycloak_min_replicas" {
  description = <<-EOT
    Keycloak replicas at idle.

    ZERO by default, and this is the single most consequential cost choice in
    the deployment. Keycloak cannot be made cheap while running: at 0.5 vCPU and
    1 GiB held continuously it consumes roughly 1.3M vCPU-seconds a month
    against a 180k free grant, which works out around 30-35 USD/month -- a third
    of the entire student credit, every month, to validate tokens for a demo
    nobody is signed in to.

    At zero it bills essentially nothing, and the cost moves to a 40-60 second
    cold start on the first sign-in. scripts/deploy-azure-student.sh warms it at
    the end of a deploy, and docs/azure-deployment.md tells you to hit the login
    page once before a live demonstration.

    Set 1 only for the duration of a demo, then set it back.
  EOT
  type        = number
  default     = 0
}

variable "keycloak_cpu" {
  description = "vCPU for Keycloak. It is a JVM; below 0.5 it fails its own startup probe."
  type        = number
  default     = 0.5
}

variable "keycloak_memory" {
  description = "Memory for Keycloak. Container Apps requires a 2:1 GiB-to-vCPU ratio."
  type        = string
  default     = "1Gi"
}

variable "enable_key_vault" {
  description = <<-EOT
    Provision Key Vault and read secrets through managed identity.

    Standard-tier Key Vault bills per 10,000 operations and is effectively free
    at demo volume, so this defaults on: it is the difference between an
    architecture that looks enterprise-ready and one that is.
  EOT
  type        = bool
  default     = true
}
