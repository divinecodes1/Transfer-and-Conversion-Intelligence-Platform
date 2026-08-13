# ============================================================================
# HTTPS ingress for the two request-serving Lambdas.
#
# The functions are addressed through CloudFront rather than by their own
# Function URLs. The distribution holds an Origin Access Control that signs
# every forwarded request with SigV4, so the functions can require AWS_IAM and
# still be reachable from a browser that carries no AWS credential.
#
# Two reasons this shape rather than a public Function URL:
#
#   1. It is tighter. A public Function URL is invocable by anyone who learns
#      the hostname; these are invocable only by this distribution, which the
#      lambda permissions below pin by ARN.
#   2. Public Function URLs are refused outright in some account states -- an
#      unverified account answers 403 to an anonymous invoke no matter how
#      correct the resource policy is. Signing sidesteps that entirely.
#
# One distribution per service, mirroring keycloak_ingress.tf. A single
# distribution with /api and /assistant behaviours would need a CloudFront
# Function to strip the prefix before the origin sees it, because the FastAPI
# apps serve their routes at the root.
# ============================================================================

resource "aws_cloudfront_origin_access_control" "lambda" {
  name                              = "${local.name}-lambda"
  description                       = "SigV4 signing for the Lambda function URLs"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  # The Function URL is a full URL; CloudFront wants the bare host.
  api_origin_host       = replace(replace(aws_lambda_function_url.api.function_url, "https://", ""), "/", "")
  assistant_origin_host = replace(replace(aws_lambda_function_url.assistant.function_url, "https://", ""), "/", "")
}

# Managed-AllViewerExceptHostHeader cannot be used with an Origin Access
# Control. It forwards every header except Host -- including Authorization --
# and OAC puts its SigV4 signature in exactly that header. When the policy
# claims Authorization, CloudFront forwards the request UNSIGNED, and a
# function URL set to AWS_IAM answers 403. Nothing in the configuration looks
# wrong; the request simply arrives without a signature.
resource "aws_cloudfront_origin_request_policy" "lambda_signed" {
  name    = "${local.name}-lambda-signed"
  comment = "All viewer headers except Host and Authorization -- OAC signs into Authorization"

  cookies_config {
    cookie_behavior = "all"
  }

  query_strings_config {
    query_string_behavior = "all"
  }

  headers_config {
    header_behavior = "allExcept"
    headers {
      items = ["host", "authorization"]
    }
  }
}

resource "aws_cloudfront_distribution" "api" {
  enabled     = true
  comment     = "${local.name} analytics API HTTPS ingress"
  price_class = "PriceClass_100"

  origin {
    domain_name              = local.api_origin_host
    origin_id                = "api"
    origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # Caching disabled: every response is entitlement-scoped, and a cache keyed
    # on anything less than the caller's identity would serve one tenant's
    # figures to another. The API does its own short-TTL caching server-side.
    cache_policy_id = data.aws_cloudfront_cache_policy.disabled.id
    # Neither Host nor Authorization may be forwarded: SigV4 is computed over
    # the origin host, and the signature itself travels in Authorization. See
    # the policy above for what that costs and how the token still arrives.
    origin_request_policy_id = aws_cloudfront_origin_request_policy.lambda_signed.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_cloudfront_distribution" "assistant" {
  enabled     = true
  comment     = "${local.name} reporting assistant HTTPS ingress"
  price_class = "PriceClass_100"

  origin {
    domain_name              = local.assistant_origin_host
    origin_id                = "assistant"
    origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id         = "assistant"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.lambda_signed.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Scoped to the distribution ARN, so the grant is to *this* distribution rather
# than to CloudFront as a service -- without SourceArn any CloudFront
# distribution in any account could invoke these functions.
resource "aws_lambda_permission" "api_cloudfront" {
  statement_id           = "AllowCloudFrontInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.api.arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "assistant_cloudfront" {
  statement_id           = "AllowCloudFrontInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.assistant.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.assistant.arn
  function_url_auth_type = "AWS_IAM"
}
