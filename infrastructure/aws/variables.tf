# ============================================================================
# Transfer & Conversion Intelligence Platform :: student-tier AWS inputs.
#
# Every default is the cheapest option that still demonstrates the architecture.
# Where a default can cost money, the comment names the cost driver.
#
# New accounts use the six-month credit-based Free Plan. Detect it with the
# current account-plan API: aws freetier get-account-plan-state.
#
# Check which you have:
#   aws freetier get-account-plan-state --region us-east-1
#   (or Billing console -> Free Tier)
#
# The design assumes the WORSE case and minimises standing charges regardless.
# ============================================================================

variable "region" {
  description = <<-EOT
    AWS region. Keep everything in one: cross-region traffic is billed, traffic
    between these services in one region is not. eu-central-1 (Frankfurt) is the
    closest to the previous deployment.
  EOT
  type        = string
  default     = "eu-central-1"
}

variable "prefix" {
  description = "Short resource-name prefix."
  type        = string
  default     = "ti"

  validation {
    # S3 buckets and ECR repositories are lower-case and alphanumeric; catching
    # it here beats a failure ninety seconds into apply.
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.prefix))
    error_message = "prefix must be 2-8 lower-case alphanumeric characters starting with a letter."
  }
}

variable "environment" {
  type    = string
  default = "student"
}

variable "owner" {
  type    = string
  default = "student"
}

# ---- Budget ----------------------------------------------------------------

variable "monthly_budget_amount" {
  description = <<-EOT
    Monthly budget in USD. Alerts only -- AWS does not stop spending when a
    budget is exceeded, and on a credit account the credit simply drains.
    Thresholds fire at 50/75/90/100%; the default 15 warns early at 7.50.
  EOT
  type        = number
  default     = 15
}

variable "free_plan_credit_budget_amount" {
  description = "Gross annual usage alert; credits are deliberately excluded from the cost calculation."
  type        = number
  default     = 90
}

variable "free_plan_expiration_date" {
  description = "Informational YYYY-MM-DD date from Billing; deployment scripts warn as it approaches."
  type        = string
  default     = ""
  validation {
    condition     = var.free_plan_expiration_date == "" || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", var.free_plan_expiration_date))
    error_message = "free_plan_expiration_date must be blank or YYYY-MM-DD."
  }
}

variable "budget_alert_emails" {
  description = "Addresses receiving budget alerts. EMPTY DISABLES THE BUDGET ENTIRELY."
  type        = list(string)
  default     = []
}

# ---- Database --------------------------------------------------------------

variable "db_instance_class" {
  description = <<-EOT
    RDS instance class. db.t4g.micro is the smallest Graviton burstable and the
    single largest standing charge here; current regional pricing applies.
  EOT
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "GB. 20 is the RDS floor and bounds the standing storage charge."
  type        = number
  default     = 20
}

variable "db_username" {
  description = "Master login. Not the application's identity -- the API uses the least-privilege reader role."
  type        = string
  default     = "transferops_admin"
}

# ---- Keycloak (EC2) --------------------------------------------------------

variable "keycloak_instance_type" {
  description = <<-EOT
    t3.micro: 2 vCPU burst, 1 GiB, x86_64. It runs continuously and consumes
    current Free Plan credit at the regional EC2 price.

    x86_64 rather than Graviton (t4g) because GitHub's runners are x86, and an
    arm64 image would have to be built under QEMU; see the note in keycloak.tf.

    Keycloak is a stateful JVM that cannot scale to zero without disruptive cold
    starts. The instance keeps authentication warm and also supplies NAT egress.
  EOT
  type        = string
  default     = "t3.micro"
}

variable "keycloak_volume_gb" {
  description = "Root volume. 8 GB is enough for the OS and one retained container image."
  type        = number
  default     = 8
}

variable "ssh_public_key" {
  description = <<-EOT
    Optional SSH key for the Keycloak host. Empty means no key pair and no SSH
    ingress at all -- use SSM Session Manager instead, which needs no open port,
    no key to lose, and logs who connected.
  EOT
  type        = string
  default     = ""
}

# ---- Registration/recovery email ------------------------------------------

variable "smtp_host" {
  description = "SMTP relay hostname. Blank disables outbound registration/recovery mail."
  type        = string
  default     = ""
}

variable "smtp_port" {
  type    = number
  default = 587
}
variable "smtp_from" {
  type    = string
  default = ""
}
variable "smtp_reply_to" {
  type    = string
  default = ""
}
variable "smtp_username" {
  type    = string
  default = ""
}
variable "smtp_password" {
  type      = string
  default   = ""
  sensitive = true
}
variable "smtp_auth" {
  type    = bool
  default = true
}
variable "smtp_ssl" {
  type    = bool
  default = false
}
variable "smtp_starttls" {
  type    = bool
  default = true
}

# ---- API (Lambda) ----------------------------------------------------------

variable "api_memory_mb" {
  description = <<-EOT
    Lambda memory, which also sets the CPU share. 1024 MB is the sweet spot for
    a Python API: enough that cold start is not dominated by interpreter
    startup, and billed per millisecond so a faster function is often cheaper
    than a smaller one.
  EOT
  type        = number
  default     = 1024
}

variable "api_timeout_seconds" {
  description = "Request ceiling. Analytics queries here are sub-second; 30s is generous and bounds a runaway."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch Logs retention. The default is "never expire", which is how log
    storage quietly becomes the largest line on a small account. 14 days is
    enough to debug a demo.
  EOT
  type        = number
  default     = 14
}

# ---- Images ----------------------------------------------------------------

variable "api_image_tag" {
  description = "Tag of the API image in ECR. The deploy script builds and pushes it."
  type        = string
  default     = "latest"
}

# ---- Application configuration ---------------------------------------------

variable "auth_mode" {
  description = "TRANSFEROPS_AUTH. 'enforce' requires a verified token; 'demo' must never be used on a public URL."
  type        = string
  default     = "enforce"

  validation {
    condition     = contains(["enforce", "demo"], var.auth_mode)
    error_message = "auth_mode must be 'enforce' or 'demo'."
  }
}

variable "keycloak_realm" {
  type    = string
  default = "transferops"
}

variable "keycloak_audience" {
  type    = string
  default = "transferops-api"
}

variable "ai_provider" {
  description = <<-EOT
    anthropic | openai | mock. 'mock' needs no key and no credits, and every AI
    surface still works -- similarity and delay risk never used a model at all.
  EOT
  type        = string
  default     = "mock"

  validation {
    condition     = contains(["anthropic", "openai", "mock"], var.ai_provider)
    error_message = "ai_provider must be one of: anthropic, openai, mock."
  }
}

variable "ai_api_key" {
  description = "Model key. Supply via TF_VAR_ai_api_key; stored as an SSM SecureString."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ai_model" {
  type    = string
  default = ""
}

variable "ai_base_url" {
  description = "OpenAI-compatible base URL. Point at Groq, Bedrock's compatible endpoint, or a local model."
  type        = string
  default     = ""
}

variable "ai_daily_request_cap" {
  type    = number
  default = 50
}

# ---- CI ---------------------------------------------------------------------

variable "github_repository" {
  description = <<-EOT
    owner/name of the repository allowed to assume the deployment role.

    This is the piece Azure could not provide: GitHub OIDC federation on AWS is
    an IAM identity provider and an IAM role INSIDE YOUR OWN ACCOUNT. It needs no
    directory administrator and no tenant policy change, so CI can actually
    deploy. Empty skips creating the role.
  EOT
  type        = string
  default     = ""
}
