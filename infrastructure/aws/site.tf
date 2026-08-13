# ============================================================================
# The console: S3 behind CloudFront.
#
# The console is a Vite SPA -- static files, no server runtime -- so this is not
# a compromise but an exact fit. CloudFront's always-free tier includes 1 TB out
# and 10M requests a month, which a demo will never approach.
#
# CloudFront rather than an S3 website endpoint, for one reason that is not
# optional: S3 website endpoints are HTTP only. The console carries a bearer
# token on every API call, and serving it over plaintext would put that token on
# the wire. CloudFront gives HTTPS on its default domain for nothing.
#
# The bucket stays private and CloudFront reaches it through Origin Access
# Control, so the objects are not separately fetchable and there is no public
# bucket policy to get wrong.
# ============================================================================

resource "aws_s3_bucket" "console" {
  bucket        = local.bucket_name
  force_destroy = true # a demo bucket must never block a teardown
}

resource "aws_s3_bucket_public_access_block" "console" {
  bucket = aws_s3_bucket.console.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "console" {
  bucket = aws_s3_bucket.console.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Documents, generated reports and exports. Separate from the console bucket so
# a public-facing distribution can never be pointed at business content.
resource "aws_s3_bucket" "documents" {
  bucket        = "${var.prefix}-documents-${var.environment}-${random_string.suffix.result}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Exports and generated reports are reproducible from the warehouse in seconds.
# Storage that only ever grows is how a free 5 GB allowance becomes a charge in
# month four.
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "expire-exports"
    status = "Enabled"
    filter { prefix = "exports/" }
    expiration { days = 7 }
  }

  rule {
    id     = "expire-generated-reports"
    status = "Enabled"
    filter { prefix = "reports/" }
    expiration { days = 30 }
  }

  # Knowledge documents feed the retrieval index: inputs, not outputs. Never
  # auto-deleted, only cooled.
  rule {
    id     = "cool-knowledge"
    status = "Enabled"
    filter { prefix = "knowledge/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

# ---- CloudFront -------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "console" {
  name                              = "${local.name}-console"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "console" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${local.name} console"
  # PriceClass_100 is North America and Europe only. All is roughly twice the
  # price to serve regions this demo has no audience in.
  price_class = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.console.bucket_regional_domain_name
    origin_id                = "console"
    origin_access_control_id = aws_cloudfront_origin_access_control.console.id
  }

  default_cache_behavior {
    target_origin_id       = "console"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # CachingOptimized. Asset filenames are content-hashed by Vite, so they are
    # safe to cache hard; index.html is handled by the error responses below and
    # by the cache-control the deploy sets on it.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # A single-page app owns its own routing: a deep link like /projects/T-017 is
  # not an object in the bucket. Without these, a refresh on any route but the
  # root returns S3's 403 instead of the app.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    # The default *.cloudfront.net certificate. A custom domain would need an
    # ACM certificate in us-east-1 and a hosted zone -- the provider alias in
    # providers.tf is already there for that.
    cloudfront_default_certificate = true
  }
}

# Only this distribution may read the bucket.
data "aws_iam_policy_document" "console_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.console.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.console.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "console" {
  bucket = aws_s3_bucket.console.id
  policy = data.aws_iam_policy_document.console_bucket.json
}
