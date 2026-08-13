# ============================================================================
# HTTPS ingress for the two request-serving Lambdas.
#
# API Gateway HTTP APIs rather than the functions' own Function URLs, for one
# empirical reason: this account refuses `lambda:InvokeFunctionUrl` outright.
# Not only anonymously -- a SigV4-signed request from a CloudFront Origin
# Access Control in the same account is refused identically, while
# `lambda:InvokeFunction` succeeds. The block is on the action, so no amount of
# policy or signing works around it; the fix is to stop using that action.
#
#   anonymous  -> Function URL (NONE)      403
#   CloudFront -> Function URL (AWS_IAM)   403   (OAC, sigv4, permission by ARN)
#   API Gateway -> InvokeFunction          200
#
# HTTP APIs are also cheaper and simpler than the REST flavour: $1.00/million
# requests with a 1M/month free tier, a $default catch-all route, and native
# CORS, so the payload format 2.0 event reaches the same uvicorn process the
# Lambda Web Adapter already runs.
# ============================================================================

locals {
  console_origin = "https://${aws_cloudfront_distribution.console.domain_name}"
}

# ---- the analytics API ------------------------------------------------------
resource "aws_apigatewayv2_api" "api" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
  description   = "HTTPS ingress for the governed analytics API"

  # CORS belongs here now that the Function URL's own cors block is gone. The
  # console is served from a different origin (its own distribution), so the
  # browser preflights every call that carries a token.
  cors_configuration {
    allow_origins  = [local.console_origin]
    allow_methods  = ["GET", "POST", "OPTIONS"]
    allow_headers  = ["authorization", "content-type", "x-request-id", "x-demo-user"]
    expose_headers = ["x-request-id"]
    max_age        = 3600
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  # The API's own timeout budget is lower than this; the ceiling only stops a
  # pathological request from holding a connection for the full Lambda limit.
  timeout_milliseconds = 29000
}

# One catch-all route. The route table is not the place to describe the API --
# FastAPI already owns its own routing, and duplicating it here would mean two
# sources of truth that drift.
resource "aws_apigatewayv2_route" "api" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

# Scoped to this API. Without source_arn the grant is to API Gateway as a
# service, which means any API in any account could invoke the function.
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# ---- the reporting assistant ------------------------------------------------
resource "aws_apigatewayv2_api" "assistant" {
  name          = "${local.name}-assistant"
  protocol_type = "HTTP"
  description   = "HTTPS ingress for the reporting assistant"

  cors_configuration {
    allow_origins  = [local.console_origin]
    allow_methods  = ["GET", "POST", "OPTIONS"]
    allow_headers  = ["authorization", "content-type", "x-request-id", "x-demo-user"]
    expose_headers = ["x-request-id"]
    max_age        = 3600
  }
}

resource "aws_apigatewayv2_integration" "assistant" {
  api_id                 = aws_apigatewayv2_api.assistant.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.assistant.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "assistant" {
  api_id    = aws_apigatewayv2_api.assistant.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.assistant.id}"
}

resource "aws_apigatewayv2_stage" "assistant" {
  api_id      = aws_apigatewayv2_api.assistant.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "assistant_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.assistant.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.assistant.execution_arn}/*/*"
}
