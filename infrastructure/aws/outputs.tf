# ============================================================================
# What the scripts and the operator need after `terraform apply`.
#
# No secret is a plain output. State holds them regardless, which is why
# terraform.tfstate is gitignored and why the enterprise path moves state into
# S3 with restricted access.
# ============================================================================

output "region" {
  value = var.region
}

output "console_url" {
  description = "Public HTTPS endpoint of the console."
  value       = "https://${aws_cloudfront_distribution.console.domain_name}"
}

output "api_url" {
  description = "HTTPS ingress for the analytics API. Swagger at /docs."
  value       = aws_apigatewayv2_stage.api.invoke_url
}

output "assistant_url" {
  description = "HTTPS ingress for the reporting assistant."
  value       = aws_apigatewayv2_stage.assistant.invoke_url
}

output "keycloak_url" {
  description = <<-EOT
    Keycloak on EC2. Admin console at /admin, realm at /realms/transferops.
    Always warm -- no cold start, unlike the previous Container Apps deployment.
  EOT
  value       = "https://${aws_cloudfront_distribution.keycloak.domain_name}"
}

output "keycloak_instance_id" {
  description = "Connect with: aws ssm start-session --target <id>"
  value       = aws_instance.keycloak.id
}

# CI resolves the host by this tag instead of pinning the id above. Changing
# the instance's user_data replaces it, and an id published to a repository
# secret then names a terminated instance; the Name tag survives the swap.
output "keycloak_name_tag" {
  description = "Name tag of the Keycloak/NAT host, stable across replacements."
  value       = aws_instance.keycloak.tags["Name"]
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "console_bucket" {
  value = aws_s3_bucket.console.id
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.id
}

output "cloudfront_distribution_id" {
  description = "Needed to invalidate index.html after a console deploy."
  value       = aws_cloudfront_distribution.console.id
}

output "ecr_api_repository" {
  value = data.aws_ecr_repository.api.repository_url
}

output "ecr_keycloak_repository" {
  value = data.aws_ecr_repository.keycloak.repository_url
}

output "api_function_name" {
  value = aws_lambda_function.api.function_name
}

output "refresh_function_name" {
  value = aws_lambda_function.refresh.function_name
}

output "assistant_function_name" { value = aws_lambda_function.assistant.function_name }
output "keycloak_rollout_document" { value = aws_ssm_document.keycloak_rollout.name }
output "warehouse_seed_document" { value = aws_ssm_document.warehouse_seed.name }

output "github_actions_role_arn" {
  description = <<-EOT
    Set as AWS_ROLE_ARN in GitHub repository secrets. Empty when
    github_repository was not supplied.

    Note what is NOT here: an access key. GitHub assumes this role with a
    short-lived OIDC token, so there is no long-lived credential to store.
  EOT
  value       = var.github_repository == "" ? "" : aws_iam_role.github_actions[0].arn
}

# ---- Operator credentials --------------------------------------------------
# Shown only via an explicit `terraform output -raw <name>`.

output "database_username" {
  value = var.db_username
}

output "database_password" {
  value     = random_password.db_master.result
  sensitive = true
}

output "loader_dsn" {
  description = <<-EOT
    Stored for the constrained SSM warehouse-seed document. RDS is private, so
    this DSN is not reachable from an operator laptop.
  EOT
  value       = local.dsn.admin
  sensitive   = true
}

output "reader_password" {
  value     = random_password.db_reader.result
  sensitive = true
}

output "auditor_password" {
  value     = random_password.db_auditor.result
  sensitive = true
}

output "ai_password" {
  value     = random_password.db_ai.result
  sensitive = true
}

output "keycloak_admin_username" {
  value = "kcadmin"
}

output "keycloak_admin_password" {
  value     = random_password.keycloak_admin.result
  sensitive = true
}

# ---- A cost summary worth reading at apply time -----------------------------
output "cost_posture" {
  description = "What this stack bills, so the number is visible rather than discovered."
  value = join("\n", [
    "CloudFront + S3     console + identity ingress; usage-based under the current plan",
    "Lambda (api + assistant + refresh) scales to zero; usage consumes Free Plan credit after any allowance",
    "Lambda (refresh)    nightly, ~seconds  negligible",
    "EC2 ${var.keycloak_instance_type} (keycloak + NAT) ALWAYS ON; current pricing draws Free Plan credit",
    "RDS ${var.db_instance_class} private, ALWAYS ON; the largest standing charge",
    "Public IPv4         one attached EIP; AWS charges 0.005 USD/hour (~3.65/month)",
    "ECR                 3 images kept per repository to cap storage growth",
    "SSM Parameter Store standard params    free (Secrets Manager would be 0.40/secret/month)",
    "CloudWatch Logs     ${var.log_retention_days}-day retention caps storage growth",
    "NAT Gateway         NOT PROVISIONED    would be ~32 USD/month",
    "",
    "Budget calculations exclude credits so alerts show gross burn before the balance disappears.",
    "Free Plan expiration configured: ${var.free_plan_expiration_date == "" ? "not set" : var.free_plan_expiration_date}",
    "Check current plan: aws freetier get-account-plan-state --region us-east-1",
  ])
}
