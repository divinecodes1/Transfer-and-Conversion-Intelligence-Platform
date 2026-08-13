# ============================================================================
# GitHub Actions -> AWS, with no stored credential.
#
# THIS IS THE THING AZURE COULD NOT DO.
#
# The Azure deployment ended with CI unable to deploy at all. Federated login
# there needs a service principal, a service principal needs an app registration
# in the Entra directory, and a university tenant sets
# allowedToCreateApps = false for everyone but an administrator. Full ownership
# of the subscription did not help: ARM rights and directory rights are separate,
# and the directory said no.
#
# On AWS the equivalent is an IAM OIDC identity provider and an IAM role, both
# of which live INSIDE THIS ACCOUNT and are created by the same credentials that
# create everything else. No directory, no tenant policy, no administrator.
#
# No access key is ever generated. GitHub mints a short-lived OIDC token scoped
# to one repository and one environment; the trust policy below accepts exactly
# that and nothing else. There is no long-lived secret to leak or rotate.
# ============================================================================

# The thumbprint argument is no longer required -- IAM validates GitHub's OIDC
# certificate against its own trust store -- so it is deliberately omitted
# rather than pinned to a value that expires and breaks the deployment.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_repository == "" ? 0 : 1

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  lifecycle {
    # An account may already have one; two providers for the same issuer is an
    # error, and this one is shared infrastructure rather than owned here.
    ignore_changes = [thumbprint_list]
  }
}

data "aws_iam_policy_document" "github_assume" {
  count = var.github_repository == "" ? 0 : 1

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # The subject is matched exactly. A workflow in another repository, or on
    # another branch, presents a different subject and is refused -- which is
    # what makes this safer than an access key that works from anywhere.
    #
    # `environment:production-demo` is listed because the deploy jobs declare
    # that environment and GitHub puts it in the subject; without it those jobs
    # fail even though the branch pattern matches.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:environment:production-demo",
        "repo:${var.github_repository}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  count = var.github_repository == "" ? 0 : 1

  name               = "${local.name}-github-actions"
  description        = "Assumed by GitHub Actions via OIDC. No access key exists."
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
  # An hour is longer than any job here runs, and shorter than a working day.
  max_session_duration = 3600
}

# What CI may do: push images, roll the two functions, publish the console.
# Scoped to this deployment's own resources -- CI can redeploy this stack and
# touch nothing else in the account.
data "aws_iam_policy_document" "github_deploy" {
  count = var.github_repository == "" ? 0 : 1

  # ECR: push images. GetAuthorizationToken cannot be resource-scoped; the
  # push itself is restricted to these two repositories.
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      aws_ecr_repository.api.arn,
      aws_ecr_repository.keycloak.arn,
    ]
  }

  # Lambda: point the functions at a new image. Not lambda:* -- CI has no
  # business changing a function's role, its environment or its permissions.
  statement {
    sid = "LambdaDeploy"
    actions = [
      "lambda:UpdateFunctionCode",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:PublishVersion",
    ]
    resources = [
      aws_lambda_function.api.arn,
      aws_lambda_function.refresh.arn,
    ]
  }

  # The console bucket, and only the console bucket. Not the documents bucket:
  # a frontend deploy has no reason to touch business content.
  statement {
    sid       = "ConsoleUpload"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.console.arn}/*"]
  }

  statement {
    sid       = "ConsoleList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.console.arn]
  }

  # Invalidate index.html after a console deploy. Without this the CDN keeps
  # serving the previous bundle and the deploy appears to have done nothing.
  statement {
    sid       = "CloudFrontInvalidate"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.console.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  count = var.github_repository == "" ? 0 : 1

  name   = "${local.name}-github-deploy"
  role   = aws_iam_role.github_actions[0].id
  policy = data.aws_iam_policy_document.github_deploy[0].json
}
