output "region" { value = var.region }
output "api_repository_url" { value = aws_ecr_repository.api.repository_url }
output "api_repository_name" { value = aws_ecr_repository.api.name }
output "keycloak_repository_url" { value = aws_ecr_repository.keycloak.repository_url }
output "keycloak_repository_name" { value = aws_ecr_repository.keycloak.name }
