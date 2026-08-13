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
  description = "Lambda Function URL. Swagger at /docs."
  value       = aws_lambda_function_url.api.function_url
}

output "keycloak_url" {
  description = <<-EOT
    Keycloak on EC2. Admin console at /admin, realm at /realms/transferops.
    Always warm -- no cold start, unlike the previous Container Apps deployment.
  EOT
  value       = "http://${aws_eip.keycloak.public_ip}:8080"
}

output "keycloak_instance_id" {
  description = "Connect with: aws ssm start-session --target <id>"
  value       = aws_instance.keycloak.id
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
  value = aws_ecr_repository.api.repository_url
}

output "ecr_keycloak_repository" {
  value = aws_ecr_repository.keycloak.repository_url
}

output "api_function_name" {
  value = aws_lambda_function.api.function_name
}

output "refresh_function_name" {
  value = aws_lambda_function.refresh.function_name
}

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
    For: python etl/run.py --engine postgres --dsn "$(terraform output -raw loader_dsn)"
    Requires allowed_client_ip to have been set, or the security group refuses it.
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
    "CloudFront + S3     console            free tier: 1TB/month out, always free",
    "Lambda (api)        ${var.api_memory_mb}MB, scales to zero   free tier: 1M requests/month, ALWAYS free",
    "Lambda (refresh)    nightly, ~seconds  negligible",
    "EC2 ${var.keycloak_instance_type} (keycloak)  ALWAYS ON          free on the legacy 12-month tier; ~6 USD/month otherwise",
    "RDS ${var.db_instance_class}      ALWAYS ON          free on the legacy 12-month tier; ~13 USD/month otherwise -- the largest charge",
    "ECR                 3 images kept      free tier: 500MB",
    "SSM Parameter Store standard params    free (Secrets Manager would be 0.40/secret/month)",
    "CloudWatch Logs     ${var.log_retention_days}-day retention     free tier: 5GB/month",
    "NAT Gateway         NOT PROVISIONED    would be ~32 USD/month",
    "",
    "Legacy 12-month free tier: roughly 0 USD/month.",
    "Credit-based tier:         roughly 20 USD/month, dominated by RDS + EC2.",
    "Check which you have:      aws freetier get-free-tier-usage --region us-east-1",
  ])
}
