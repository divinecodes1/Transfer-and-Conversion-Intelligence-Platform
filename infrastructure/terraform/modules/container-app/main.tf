# Container Apps environment, the API app, a scheduled job, and the static site.
#
# The environment uses a workload-profiles v2 setup with the built-in
# Consumption profile, which is what Microsoft recommends for new deployments
# and what keeps scale-to-zero available. Consumption bills per vCPU-second and
# GiB-second actually used, against a monthly free grant; a demo nobody is
# hitting bills nothing at all.
#
# min_replicas = 0 is the whole cost model. The trade is a cold start of a few
# seconds on the first request after idle. For a portfolio demonstration that is
# the right side of the trade -- and the Static Web App in front is always warm,
# so the page paints immediately and only the data waits.

variable "environment_name" { type = string }
variable "api_app_name" { type = string }
variable "job_name" { type = string }
variable "static_site_name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }

variable "log_analytics_workspace_id" { type = string }
variable "identity_id" { type = string }
variable "identity_client_id" { type = string }

variable "image" { type = string }
variable "registry_server" { type = string }
variable "registry_username" {
  type      = string
  sensitive = true
}
variable "registry_password" {
  type      = string
  sensitive = true
}
variable "registry_uses_identity" { type = bool }

variable "min_replicas" { type = number }
variable "max_replicas" { type = number }
variable "cpu" { type = number }
variable "memory" { type = string }

variable "secrets" {
  type      = map(string)
  sensitive = true
}
variable "env" { type = map(string) }

variable "db_host" { type = string }
variable "db_name" { type = string }
variable "db_admin" { type = string }

variable "keycloak_app_name" { type = string }
variable "keycloak_image" { type = string }
variable "keycloak_database_name" { type = string }
variable "keycloak_admin_username" { type = string }
variable "keycloak_admin_password" {
  type      = string
  sensitive = true
}
variable "keycloak_realm" { type = string }
variable "keycloak_audience" { type = string }
variable "keycloak_min_replicas" { type = number }
variable "keycloak_cpu" { type = number }
variable "keycloak_memory" { type = string }
variable "keycloak_smtp" { type = map(string) }

locals {
  # DSNs are assembled here and stored whole as secrets. A connection string
  # cannot be composed at runtime from a separate password secret, so the
  # alternative would be putting the password in a plain environment variable --
  # visible in the portal, in `az containerapp show`, and in any log that dumps
  # the environment.
  #
  # sslmode=require is not decoration: without it libpq will happily fall back
  # to plaintext, and the traffic crosses shared Azure networking.
  dsn = {
    admin   = "postgresql://${var.db_admin}:${urlencode(var.secrets["db-admin-password"])}@${var.db_host}:5432/${var.db_name}?sslmode=require"
    reader  = "postgresql://transferops_reader:${urlencode(var.secrets["db-reader-password"])}@${var.db_host}:5432/${var.db_name}?sslmode=require"
    auditor = "postgresql://transferops_auditor:${urlencode(var.secrets["db-auditor-password"])}@${var.db_host}:5432/${var.db_name}?sslmode=require"
    ai      = "postgresql://transferops_ai:${urlencode(var.secrets["db-ai-password"])}@${var.db_host}:5432/${var.db_name}?sslmode=require"
  }

  # Everything the containers hold as a secret, in one place so the app and the
  # job cannot drift apart.
  # Keycloak takes a JDBC URL, not a libpq DSN, and wants the credentials as
  # separate variables.
  keycloak_jdbc_url = "jdbc:postgresql://${var.db_host}:5432/${var.keycloak_database_name}?sslmode=require"

  container_secrets = merge(
    {
      "dsn-admin"   = local.dsn.admin
      "dsn-reader"  = local.dsn.reader
      "dsn-auditor" = local.dsn.auditor
      "dsn-ai"      = local.dsn.ai
    },
    var.secrets["ai-api-key"] != "" ? { "ai-api-key" = var.secrets["ai-api-key"] } : {},
    var.registry_password != "" ? { "registry-password" = var.registry_password } : {},
  )

  # Empty values are dropped: Container Apps treats an empty env var as set, and
  # the application's own "is this configured?" checks would then see a
  # configured-but-blank issuer instead of an absent one.
  plain_env = { for k, v in var.env : k => v if v != "" }
}

resource "azurerm_container_app_environment" "this" {
  name                       = var.environment_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app" "api" {
  name                         = var.api_app_name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [1]
    content {
      server = var.registry_server
      # ACR is pulled with the managed identity -- no credential to rotate.
      # A third-party registry still needs a username/password pair.
      identity             = var.registry_uses_identity ? var.identity_id : null
      username             = var.registry_uses_identity ? null : var.registry_username
      password_secret_name = var.registry_uses_identity ? null : "registry-password"
    }
  }

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    # HTTP is redirected, never served. The console sends a bearer token on
    # every request; a plaintext hop would put it on the wire.
    allow_insecure_connections = false

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "api"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      command = ["uvicorn"]
      args = [
        "api.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        # One worker. Two would double memory inside a 0.5 GiB container to
        # serve a demo; Container Apps scales by adding replicas instead.
        "--workers", "1",
      ]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "TRANSFEROPS_DSN"
        secret_name = "dsn-admin"
      }
      env {
        name        = "TRANSFEROPS_API_DSN"
        secret_name = "dsn-reader"
      }
      env {
        name        = "TRANSFEROPS_AUDIT_DSN"
        secret_name = "dsn-auditor"
      }
      env {
        name        = "TRANSFEROPS_AI_DSN"
        secret_name = "dsn-ai"
      }

      dynamic "env" {
        for_each = contains(keys(local.container_secrets), "ai-api-key") ? [1] : []
        content {
          name        = "TRANSFEROPS_AI_API_KEY"
          secret_name = "ai-api-key"
        }
      }

      # The realm the API verifies tokens against. api/auth.py builds both the
      # issuer and the JWKS URL from these three values, so pointing them at the
      # Keycloak Container App is the entire cloud configuration -- no code
      # change and no second identity provider.
      env {
        name  = "KEYCLOAK_URL"
        value = "https://${azurerm_container_app.keycloak.ingress[0].fqdn}"
      }
      env {
        name  = "KEYCLOAK_REALM"
        value = var.keycloak_realm
      }
      env {
        name  = "KEYCLOAK_AUDIENCE"
        value = var.keycloak_audience
      }

      # /health does a real warehouse round-trip, so a replica that is up but
      # cannot reach the metric layer is taken out of rotation rather than
      # serving errors.
      liveness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        initial_delay           = 15
        interval_seconds        = 30
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 10
        failure_count_threshold = 3
      }
    }

    # Scale on concurrent requests. The default is 10 per replica, which for a
    # read-only analytics API backed by a burstable database is already generous.
    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = 20
    }
  }
}

# ---- Identity provider ------------------------------------------------------
# Keycloak, running as its own Container App against its own database on the
# shared server.
#
# It scales to zero like everything else here, and unlike everything else here
# that has a visible cost: the first sign-in after an idle period waits 40-60
# seconds for the JVM to start. That is the deliberate trade. Keeping one replica
# warm is roughly a third of the entire student credit per month, spent almost
# entirely on idle time.
#
# What this buys, and why it is not replaced by a cloud identity service: the
# branded realm, the login and email themes, self-registration, email
# verification and password recovery are part of what the platform demonstrates.
# A tenant login page would remove all of it.
resource "azurerm_container_app" "keycloak" {
  name                         = var.keycloak_app_name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [1]
    content {
      server               = var.registry_server
      identity             = var.registry_uses_identity ? var.identity_id : null
      username             = var.registry_uses_identity ? null : var.registry_username
      password_secret_name = var.registry_uses_identity ? null : "registry-password"
    }
  }

  secret {
    name  = "keycloak-admin-password"
    value = var.keycloak_admin_password
  }

  secret {
    name  = "keycloak-db-password"
    value = var.secrets["db-admin-password"]
  }

  dynamic "secret" {
    for_each = var.registry_password != "" ? [1] : []
    content {
      name  = "registry-password"
      value = var.registry_password
    }
  }

  ingress {
    external_enabled           = true
    target_port                = 8080
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.keycloak_min_replicas
    # Exactly one. Keycloak clusters via Infinispan and a second replica without
    # a configured cache stack serves inconsistent sessions -- a user would be
    # signed in on one request and out on the next.
    max_replicas = 1

    container {
      name   = "keycloak"
      image  = var.keycloak_image
      cpu    = var.keycloak_cpu
      memory = var.keycloak_memory

      # `start` rather than `start-dev`: production mode enforces a real
      # database and refuses the in-memory H2 store, so a restart cannot
      # silently discard the realm and every registered user.
      command = ["/opt/keycloak/bin/kc.sh"]
      args    = ["start", "--optimized", "--import-realm"]

      env {
        name  = "KC_DB"
        value = "postgres"
      }
      env {
        name  = "KC_DB_URL"
        value = local.keycloak_jdbc_url
      }
      env {
        name  = "KC_DB_USERNAME"
        value = var.db_admin
      }
      env {
        name        = "KC_DB_PASSWORD"
        secret_name = "keycloak-db-password"
      }
      env {
        name  = "KC_BOOTSTRAP_ADMIN_USERNAME"
        value = var.keycloak_admin_username
      }
      env {
        name        = "KC_BOOTSTRAP_ADMIN_PASSWORD"
        secret_name = "keycloak-admin-password"
      }
      env {
        name  = "KC_HOSTNAME_STRICT"
        value = "false"
      }
      # Container Apps terminates TLS at the ingress and forwards plain HTTP.
      # Without this Keycloak sees an http:// request, decides the deployment is
      # insecure and refuses to serve the admin console.
      env {
        name  = "KC_PROXY_HEADERS"
        value = "xforwarded"
      }
      env {
        name  = "KC_HTTP_ENABLED"
        value = "true"
      }
      env {
        name  = "KC_HEALTH_ENABLED"
        value = "true"
      }

      # Resolved into the realm's redirectUris and webOrigins during import, so
      # the deployed console is an allowed origin without anyone opening the
      # admin console. The realm file in the image carries the placeholder; this
      # supplies the value.
      env {
        name  = "TRANSFEROPS_WEB_ORIGIN"
        value = "https://${azurerm_static_web_app.web.default_host_name}"
      }

      # The realm's smtpServer block is written with ${KEYCLOAK_SMTP_*}
      # placeholders, and realm import fails outright if they do not resolve --
      # so every one of them is supplied even though the student deployment has
      # no mail relay.
      #
      # The consequence is honest and worth knowing: with no SMTP host, Keycloak
      # cannot send a verification message, so SELF-REGISTRATION DOES NOT
      # COMPLETE in Azure. Locally, Mailpit catches the mail and the flow works
      # end to end. Point these at a real relay to restore it in the cloud;
      # docs/azure-deployment.md says so, and the operator account is granted
      # directly in tr_gov instead.
      dynamic "env" {
        for_each = var.keycloak_smtp
        content {
          name  = env.key
          value = env.value
        }
      }

      # Keycloak's own health endpoints, on the management port. The startup
      # budget is deliberately long: a cold JVM against a burstable database
      # legitimately takes most of a minute, and a tighter probe would restart
      # it in a loop it can never win.
      startup_probe {
        transport               = "HTTP"
        port                    = 9000
        path                    = "/health/started"
        interval_seconds        = 10
        failure_count_threshold = 30
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 9000
        path                    = "/health/live"
        initial_delay           = 60
        interval_seconds        = 30
        failure_count_threshold = 5
      }
    }

    # One concurrent request is enough to wake it. Sign-in is the only traffic
    # it takes, and the API caches the signing keys for five minutes.
    http_scale_rule {
      name                = "http-signin"
      concurrent_requests = 10
    }
  }
}

# The scheduled pipeline. A Container Apps Job runs on a cron trigger, executes,
# and stops -- there is no idle cost and no cluster to keep alive, which is the
# whole reason Airflow is deferred to the enterprise architecture.
resource "azurerm_container_app_job" "refresh" {
  name                         = var.job_name
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.this.id
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  # A refresh that has not finished in ten minutes is stuck, not slow.
  replica_timeout_in_seconds = 600
  replica_retry_limit        = 1

  schedule_trigger_config {
    # 02:00 UTC daily. Off-peak, once a day: the warehouse vintage moves daily,
    # so refreshing more often would recompute identical narratives and bill for
    # the privilege.
    cron_expression          = "0 2 * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [1]
    content {
      server               = var.registry_server
      identity             = var.registry_uses_identity ? var.identity_id : null
      username             = var.registry_uses_identity ? null : var.registry_username
      password_secret_name = var.registry_uses_identity ? null : "registry-password"
    }
  }

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  template {
    container {
      name   = "refresh"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      # Warms the AI caches against the current warehouse vintage. In mock mode
      # this still runs and still produces deterministic narratives, so the
      # scheduled-pipeline story holds with no model configured and no spend.
      command = ["python"]
      args    = ["-m", "ai.refresh", "--job", "all", "--trigger", "scheduled"]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "TRANSFEROPS_DSN"
        secret_name = "dsn-admin"
      }
      env {
        name        = "TRANSFEROPS_API_DSN"
        secret_name = "dsn-reader"
      }
      env {
        name        = "TRANSFEROPS_AI_DSN"
        secret_name = "dsn-ai"
      }

      dynamic "env" {
        for_each = contains(keys(local.container_secrets), "ai-api-key") ? [1] : []
        content {
          name        = "TRANSFEROPS_AI_API_KEY"
          secret_name = "ai-api-key"
        }
      }
    }
  }
}

# The console. Free tier: 100 GB bandwidth a month and a managed certificate on
# the default hostname. The build is a Vite SPA -- static files with no server
# runtime -- so nothing here needs to scale or wake up.
resource "azurerm_static_web_app" "web" {
  name                = var.static_site_name
  resource_group_name = var.resource_group_name
  # Static Web Apps Free is offered in a subset of regions; westeurope is one.
  location = var.location

  sku_tier = "Free"
  sku_size = "Free"

  tags = var.tags
}

output "api_fqdn" { value = azurerm_container_app.api.ingress[0].fqdn }
output "api_url" { value = "https://${azurerm_container_app.api.ingress[0].fqdn}" }
output "keycloak_url" { value = "https://${azurerm_container_app.keycloak.ingress[0].fqdn}" }
output "keycloak_app_name" { value = azurerm_container_app.keycloak.name }
output "web_hostname" { value = azurerm_static_web_app.web.default_host_name }
output "web_url" { value = "https://${azurerm_static_web_app.web.default_host_name}" }
output "web_api_key" {
  value     = azurerm_static_web_app.web.api_key
  sensitive = true
}
output "environment_id" { value = azurerm_container_app_environment.this.id }
output "job_name" { value = azurerm_container_app_job.refresh.name }
