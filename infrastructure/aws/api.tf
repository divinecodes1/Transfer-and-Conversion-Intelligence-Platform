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
      APP_ENV                  = var.environment
      TRANSFEROPS_AUTH         = var.auth_mode
      TRANSFEROPS_LOG_FORMAT   = "json"
      TRANSFEROPS_LOG_LEVEL    = "INFO"
      TRANSFEROPS_DSN          = local.dsn.admin
      TRANSFEROPS_API_DSN      = local.dsn.reader
      TRANSFEROPS_AUDIT_DSN    = local.dsn.auditor
      TRANSFEROPS_AI_DSN       = local.dsn.ai
      TRANSFEROPS_AI_PROVIDER  = var.ai_provider
      TRANSFEROPS_AI_DAILY_CAP = tostring(var.ai_daily_request_cap)
      # The API verifies this signature; the scheduled job produces it. Unset,
      # POST /ai/refresh refuses everything rather than defaulting to open.
      TRANSFEROPS_AI_CRON_SECRET   = random_password.ai_cron.result
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

  memory_size = 512
  # Fifteen minutes, the Lambda ceiling. A warm is one model call per narrative
  # per scope plus the risk batches, and on a throttled tier most of that time
  # is spent waiting for a token window rather than generating -- a measured run
  # takes about 4 minutes. The old 300s was a coin flip, and a job killed
  # mid-run leaves rows in tr_ai.run_log stuck at 'running', which reads as a
  # hang rather than a timeout.
  timeout       = 900
  architectures = ["x86_64"]

  # No image_config: this function runs the SAME uvicorn command the API runs.
  #
  # Overriding the command with a batch process (`python -m ai.refresh`, then
  # `python -m ai.trigger`) was the shape of the old bug. This image serves
  # through the AWS Lambda Web Adapter, which answers the invocation by
  # proxying it to a web server on AWS_LWA_PORT. Replace that server with a
  # script and nothing is listening: the work may run as a side effect of the
  # container starting, but the invocation itself is reported as a failure and
  # retried, which is why the run log shows the same night four times over.
  #
  # So the schedule delivers an event instead, and the adapter's pass-through
  # mode posts it to a real route. See aws_cloudwatch_event_target.nightly.

  environment {
    variables = merge(local.app_environment, {
      # Non-HTTP events (an EventBridge payload is one) are POSTed here rather
      # than to the default /events. The whole refresh then runs in-process
      # behind the governed route, exactly as an admin-triggered one does.
      AWS_LWA_PASS_THROUGH_PATH = "/ai/refresh"

      # Only this function retries a throttled provider, because it is the only
      # caller with nobody waiting on it. A dashboard request that waits is
      # worse than one that degrades, so the API keeps the default of one
      # attempt and falls back to a deterministic surface.
      #
      # The numbers come from what Groq's free tier actually reports: 8000
      # tokens per minute in a continuously refilling bucket, over a hard 200000
      # per day. A nightly warm is roughly thirteen calls, so it cannot fit in
      # one minute-window -- the fix is to wait for the next one rather than to
      # fail. Hence a 60s ceiling on the backoff: one full window. Retry-After
      # still wins when the provider sends it.
      #
      # Backoff cannot rescue the daily cap, and is not meant to: when the day's
      # tokens are gone the provider asks for minutes, the job spends its
      # attempts, records the scope as rate-limited and moves on. Tomorrow's
      # schedule is the retry.
      TRANSFEROPS_AI_RETRY_ATTEMPTS = "4"
      TRANSFEROPS_AI_RETRY_MAX_WAIT = "60"

      # The single biggest lever on both limits, and the least obvious.
      #
      # Groq bills the RESERVATION, not the usage: a three-word prompt sent with
      # max_tokens=4000 is charged "Requested 4073" against the quota and
      # refused when that does not fit. The platform default of 4000 is sized
      # for the Copilot, where an answer may genuinely run long. A nightly
      # briefing is about 250 words and a risk batch a few hundred tokens of
      # JSON, so four fifths of every reservation here was being paid for
      # nothing -- ~65000 tokens a night against a 200000 daily cap, most of it
      # never generated.
      #
      # 2000 still leaves roughly four times the headroom either job has ever
      # needed, so nothing truncates; it simply stops reserving what it will not
      # use.
      TRANSFEROPS_AI_MAX_TOKENS = "2000"

      # And it stops itself before the 900s ceiling does, leaving time to close
      # the run row. A process killed between start_run and finish_run leaves
      # 'running' on the automation screen, which reads as a hang rather than a
      # slow night.
      #
      # This is ONE budget for the whole run, checked before every model call.
      # At 700 it was neither -- each job took the budget afresh and the check
      # sat between scopes -- and the first real scheduled night walked past it
      # and was killed by the ceiling at 900706ms.
      #
      # 650 leaves honest margin: the check can pass with a call about to start,
      # and that call can spend its full retry allowance of 3 x 60s before
      # returning, so the true worst case is 650 + 180 = 830 against 900.
      TRANSFEROPS_AI_REFRESH_BUDGET = "650"

      # For ai/trigger.py, which is still how an operator fires a refresh by
      # hand. The schedule no longer uses it: a request through the gateway is
      # cut off at 29s (api_ingress.tf) and this job takes minutes.
      TRANSFEROPS_API = aws_apigatewayv2_stage.api.invoke_url
    })
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

  # The request the adapter will make: POST /ai/refresh with this as the body.
  #
  # The secret travels in the payload rather than as an HMAC over it, because
  # this constant is fixed at plan time and Terraform cannot compute an HMAC.
  # Nothing is given up -- the endpoint compares it in constant time and
  # possession of the secret is the authorisation either way -- and it never
  # leaves AWS: EventBridge hands the payload straight to Lambda.
  input = jsonencode({
    job     = "all"
    trigger = "scheduled"
    key     = random_password.ai_cron.result
  })
}

# Async invocations are retried twice by default, so a refresh that fails
# halfway is a refresh that runs three times and bills for it. Once is the right
# number here: the failure is recorded in tr_ai.run_log for the automation
# screen, and tomorrow's schedule is the retry.
resource "aws_lambda_function_event_invoke_config" "refresh" {
  function_name          = aws_lambda_function.refresh.function_name
  maximum_retry_attempts = 0
}

resource "aws_lambda_permission" "nightly" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.refresh.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nightly.arn
}
