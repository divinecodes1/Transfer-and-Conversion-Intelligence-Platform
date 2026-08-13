locals {
  name = "${var.prefix}-${var.environment}"
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "keycloak" {
  name                 = "${local.name}-keycloak"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Keep the three most recent rebuildable images."
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
    action       = { type = "expire" }
  }] })
}

resource "aws_ecr_lifecycle_policy" "keycloak" {
  repository = aws_ecr_repository.keycloak.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Keep the three most recent rebuildable images."
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
    action       = { type = "expire" }
  }] })
}
