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
# A Function URL rather than API Gateway: HTTPS, a stable hostname, IAM or no
# auth, and no per-request charge on top of Lambda's own. API Gateway would add
# ~1 USD per million requests and a REST/HTTP API to configure, for features
# (usage plans, request validation, custom domains) this demo does not use.
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

# Logs only. Note what is NOT attached: no VPC access (the function runs outside
# the VPC on purpose), no broad S3, no ec2:*. The database credential arrives as
# an environment variable resolved from SSM at deploy time, so the function needs
# no runtime AWS permission to read it either.
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
  # arm64 is roughly 20% cheaper per millisecond than x86_64 and the image is
  # built for it. Free-tier seconds go further on the same architecture.
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
      TRANSFEROPS_API              = aws_lambda_function_url.api.function_url
      TRANSFEROPS_WEB_ORIGIN       = "https://${aws_cloudfront_distribution.console.domain_name}"
      TRANSFEROPS_AI_PROVIDER      = var.ai_provider
      TRANSFEROPS_AI_DAILY_CAP     = tostring(var.ai_daily_request_cap)
      },
      var.ai_model != "" ? { TRANSFEROPS_AI_MODEL = var.ai_model } : {},
      var.ai_base_url != "" ? { TRANSFEROPS_AI_BASE_URL = var.ai_base_url } : {},
    var.ai_api_key != "" ? { TRANSFEROPS_AI_API_KEY = var.ai_api_key } : {})
  }

  depends_on = [aws_iam_role_policy_attachment.api_logs, aws_cloudwatch_log_group.assistant]
  lifecycle { ignore_changes = [image_uri] }
}

resource "aws_lambda_function_url" "assistant" {
  function_name      = aws_lambda_function.assistant.function_name
  authorization_type = "NONE"
  cors {
    allow_origins = ["https://${aws_cloudfront_distribution.console.domain_name}"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["authorization", "content-type", "x-request-id"]
    max_age       = 3600
  }
}

# Public HTTPS endpoint. AWS_IAM would be tighter, but the console is a browser
# SPA and the platform's own authentication -- a verified Keycloak token checked
# in api/auth.py, with entitlements enforced by row-level security -- is the
# boundary that matters. Putting IAM in front would mean signing every request
# with SigV4 from the browser, which needs credentials in the browser.
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"

  cors {
    allow_origins  = ["https://${aws_cloudfront_distribution.console.domain_name}"]
    allow_methods  = ["GET", "POST"]
    allow_headers  = ["authorization", "content-type", "x-request-id", "x-demo-user"]
    expose_headers = ["x-request-id"]
    max_age        = 3600
  }
}

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
