# ============================================================================
# Secrets: SSM Parameter Store, not Secrets Manager.
#
# Secrets Manager is 0.40 USD per secret per month. Six secrets is 2.40/month --
# eight percent of a 30 USD budget, permanently, for rotation and cross-account
# sharing this demo does not use.
#
# SSM standard parameters are free, including SecureString encrypted with the
# account's AWS-managed KMS key. The capability gap that matters is automatic
# rotation, which nothing here does anyway; aws/migration-to-enterprise.md says
# where Secrets Manager earns its price.
#
# These are the durable copy. The Lambda functions receive their connection
# strings as environment variables resolved at deploy time -- so the running
# function needs no AWS permission at all to read a secret, and the parameters
# below are what the EC2 host and the operator read.
# ============================================================================

resource "aws_ssm_parameter" "db_master_password" {
  name        = "/${local.name}/db-master-password"
  description = "RDS master password. Generated; never written to a file."
  type        = "SecureString"
  value       = random_password.db_master.result
}

resource "aws_ssm_parameter" "db_reader_password" {
  name        = "/${local.name}/db-reader-password"
  description = "Least-privilege reader role. Created by the loader, used by the API."
  type        = "SecureString"
  value       = random_password.db_reader.result
}

resource "aws_ssm_parameter" "db_auditor_password" {
  name  = "/${local.name}/db-auditor-password"
  type  = "SecureString"
  value = random_password.db_auditor.result
}

resource "aws_ssm_parameter" "db_ai_password" {
  name  = "/${local.name}/db-ai-password"
  type  = "SecureString"
  value = random_password.db_ai.result
}

resource "aws_ssm_parameter" "keycloak_admin_password" {
  name        = "/${local.name}/keycloak-admin-password"
  description = "Keycloak bootstrap admin. Read by the instance role at boot."
  type        = "SecureString"
  value       = random_password.keycloak_admin.result
}

# Only created when a key is supplied. An empty SecureString is rejected, and a
# parameter holding "" would be indistinguishable from a real but blank key.
resource "aws_ssm_parameter" "ai_api_key" {
  count = var.ai_api_key == "" ? 0 : 1

  name        = "/${local.name}/ai-api-key"
  description = "Model provider key. Absent means the platform runs in mock mode."
  type        = "SecureString"
  value       = var.ai_api_key
}

# The loader DSN, so seed-demo-data.sh does not have to reassemble it from four
# separate lookups and get the escaping wrong.
resource "aws_ssm_parameter" "loader_dsn" {
  name        = "/${local.name}/loader-dsn"
  description = "Admin DSN for etl/run.py. Requires allowed_client_ip to reach it."
  type        = "SecureString"
  value       = local.dsn.admin
}
