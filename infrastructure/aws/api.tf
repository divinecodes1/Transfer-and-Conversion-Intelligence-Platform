# ============================================================================
# The API, on Lambda.
#
# This is what makes the deployment nearly free. Lambda scales to zero properly
# -- not "one small instance", actually zero. A demo nobody is hitting has no
# Lambda compute duration, while requests still count against the current plan.
#
# The application does not know. AWS Lambda Web Adapter (see
# infrastructure/docker/lambda/Dockerfile) runs the same `uvicorn api.main:app`
# the container runs locally, so api/main.py has no handler, no Mangum import,
# and tests/api_checks.py still drives the same ASGI app the deployment serves.
#
# An API Gateway HTTP API rather than a Function URL, and not by preference:
# this account refuses `lambda:InvokeFunctionUrl` for every caller. Anonymous
# and SigV4-signed-by-CloudFront requests are both answered 403 while
# `lambda:InvokeFunction` succeeds, so the block is on the action and no policy
# or signature routes around it. HTTP APIs cost ~1 USD per million requests
# with a 1M/month free tier, which is immaterial here. See api_ingress.tf.
# ============================================================================

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = var.log_retention_days
}

# ---- Execution role ---------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Logs, plus the VPC access the managed policy grants: the API runs inside the
# private subnets because RDS has no public ingress, and reaches the internet
# through the EC2 NAT instance rather than a NAT Gateway.
#
# Note what is still NOT attached: no broad S3, no ec2:*, no ssm:*. The database
# credential arrives as an environment variable resolved from SSM at deploy
# time, so the function needs no runtime AWS permission to read it either.
resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "api_vpc" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Blob storage for generated reports and knowledge documents, scoped to the one
# bucket. Read and write, nothing else, nowhere else.
data "aws_iam_policy_document" "api_documents" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
  }
}

resource "aws_iam_role_policy" "api_documents" {
  name   = "${local.name}-api-documents"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_documents.json
}

# ---- The function -----------------------------------------------------------

locals {
  # Shared by the API and the scheduled job, so the two cannot drift apart on a
  # connection string or an auth setting.
  app_environment = merge(
    {
      APP_ENV                      = var.environment
      TRANSFEROPS_AUTH             = var.auth_mode
      TRANSFEROPS_LOG_FORMAT       = "json"
      TRANSFEROPS_LOG_LEVEL        = "INFO"
      TRANSFEROPS_DSN              = local.dsn.admin
      TRANSFEROPS_API_DSN          = local.dsn.reader
      TRANSFEROPS_AUDIT_DSN        = local.dsn.auditor
      TRANSFEROPS_AI_DSN           = local.dsn.ai
      TRANSFEROPS_AI_PROVIDER      = var.ai_provider
      TRANSFEROPS_AI_DAILY_CAP     = tostring(var.ai_daily_request_cap)
      TRANSFEROPS_WEB_ORIGIN       = "https://${aws_cloudfront_distribution.console.domain_name}"
      KEYCLOAK_URL                 = "https://${aws_cloudfront_distribution.keycloak.domain_name}"
      KEYCLOAK_JWKS_URL            = "http://${aws_instance.keycloak.private_ip}:8080"
      KEYCLOAK_REALM               = var.keycloak_realm
      KEYCLOAK_AUDIENCE            = var.keycloak_audience
      TRANSFEROPS_DOCUMENTS_BUCKET = aws_s3_bucket.documents.id
    },
    var.ai_model != "" ? { TRANSFEROPS_AI_MODEL = var.ai_model } : {},
    var.ai_base_url != "" ? { TRANSFEROPS_AI_BASE_URL = var.ai_base_url } : {},
    var.ai_api_key != "" ? { TRANSFEROPS_AI_API_KEY = var.ai_api_key } : {},
  )
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.api.repository_url}:${var.api_image_tag}"

  memory_size = var.api_memory_mb
  timeout     = var.api_timeout_seconds
  # x86_64, matching the image. arm64 would be roughly 20% cheaper per
  # millisecond, but the build in scripts/deploy-aws-student.ps1 pins
  # --platform linux/amd64; the two must agree or CreateFunction refuses the
  # image, so changing one without the other is a broken deployment.
  architectures = ["x86_64"]

  environment {
    variables = local.app_environment
  }

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.api_logs,
    aws_iam_role_policy_attachment.api_vpc,
    aws_cloudwatch_log_group.api,
    aws_route.private_egress,
  ]

  lifecycle {
    # CI updates the image out of band. Without this, the next `terraform apply`
    # would propose rolling production back to whatever tag the tfvars names.
    ignore_changes = [image_uri]
  }
}

# The assistant uses the same tested image with a different ASGI command. It is
# intentionally outside the VPC: it reaches the governed API over HTTPS and is
# never given a warehouse credential.
resource "aws_cloudwatch_log_group" "assistant" {
  name              = "/aws/lambda/${local.name}-assistant"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "assistant" {
  function_name = "${local.name}-assistant"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
  memory_size   = 1024
  timeout       = 60
  architectures = ["x86_64"]

  image_config {
    command = ["uvicorn", "agent.app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
  }

  environment {
    variables = merge({
      APP_ENV                      = var.environment
      AWS_LWA_PORT                 = "8100"
      AWS_LWA_READINESS_CHECK_PATH = "/healthz"
      # Through the gateway, like every other caller. The assistant forwards the
      # end user's Keycloak token, so it must reach the API by the same governed
      # path a browser does rather than by a privileged side door.
      TRANSFEROPS_API          = aws_apigatewayv2_stage.api.invoke_url
      TRANSFEROPS_WEB_ORIGIN   = "https://${aws_cloudfront_distribution.console.domain_name}"
      TRANSFEROPS_AI_PROVIDER  = var.ai_provider
      TRANSFEROPS_AI_DAILY_CAP = tostring(var.ai_daily_request_cap)
      },
      var.ai_model != "" ? { TRANSFEROPS_AI_MODEL = var.ai_model } : {},
      var.ai_base_url != "" ? { TRANSFEROPS_AI_BASE_URL = var.ai_base_url } : {},
    var.ai_api_key != "" ? { TRANSFEROPS_AI_API_KEY = var.ai_api_key } : {})
  }

  depends_on = [aws_iam_role_policy_attachment.api_logs, aws_cloudwatch_log_group.assistant]
  lifecycle { ignore_changes = [image_uri] }
}

# Neither function has a Function URL. Both are fronted by an API Gateway HTTP
# API instead (api_ingress.tf), which carries the CORS configuration that used
# to live here. See that file for why: this account refuses
# `lambda:InvokeFunctionUrl` for every caller, signed or not.
#
# The platform's own authentication remains the boundary that matters -- a
# verified Keycloak token checked in api/auth.py, with entitlements enforced by
# row-level security. The ingress governs who may reach the endpoint, never who
# may see which rows.

# ---- The nightly pipeline ---------------------------------------------------
# Same image, different command. A Container Apps Job on Azure; here a Lambda on
# a schedule. Either way it runs for seconds and stops, which is why no Airflow
# cluster is provisioned -- see aws/migration-to-enterprise.md.

resource "aws_cloudwatch_log_group" "refresh" {
  name              = "/aws/lambda/${local.name}-refresh"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "refresh" {
  function_name = "${local.name}-refresh"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.api.repository_url}:${var.api_image_tag}"

  memory_size   = 512
  timeout       = 300
  architectures = ["x86_64"]

  image_config {
    # Overrides the Dockerfile CMD: run the refresh module instead of serving.
    # In mock mode this still produces deterministic narratives, so the
    # scheduled-pipeline story holds with no model configured and no spend.
    command = ["python", "-m", "ai.refresh", "--job", "all", "--trigger", "scheduled"]
  }

  environment {
    variables = local.app_environment
  }

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  depends_on = [aws_cloudwatch_log_group.refresh, aws_iam_role_policy_attachment.api_vpc, aws_route.private_egress]

  lifecycle {
    ignore_changes = [image_uri]
  }
}

resource "aws_cloudwatch_event_rule" "nightly" {
  name = "${local.name}-nightly-refresh"
  # 02:00 UTC daily. The warehouse vintage moves daily, so a more frequent
  # refresh would recompute identical narratives and bill for the privilege.
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "nightly" {
  rule = aws_cloudwatch_event_rule.nightly.name
  arn  = aws_lambda_function.refresh.arn
}

resource "aws_lambda_permission" "nightly" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.refresh.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nightly.arn
}
