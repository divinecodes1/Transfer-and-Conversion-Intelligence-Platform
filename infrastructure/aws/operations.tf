# Fixed SSM documents keep deployment automation repeatable without granting CI
# permission to execute arbitrary shell commands on the instance.
resource "aws_ssm_document" "keycloak_rollout" {
  name            = "${local.name}-keycloak-rollout"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Roll the approved Keycloak image and HTTPS hostname"
    parameters = {
      ImageUri  = { type = "String", allowedPattern = "^[0-9]+\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9/_-]+:[A-Za-z0-9._-]+$" }
      PublicUrl = { type = "String", allowedPattern = "^https://[a-z0-9.-]+\\.cloudfront\\.net$" }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "rollout"
      inputs = {
        timeoutSeconds = "900"
        runCommand = [
          "set -euo pipefail",
          "IMAGE='{{ ImageUri }}'",
          "PUBLIC_URL='{{ PublicUrl }}'",
          "REGISTRY=\"$${IMAGE%%/*}\"",
          "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin \"$REGISTRY\"",
          "docker pull \"$IMAGE\"",
          "printf 'KEYCLOAK_IMAGE=%s\\n' \"$IMAGE\" > /etc/transferops/keycloak-image.env",
          "sed -i \"s|^KC_HOSTNAME=.*|KC_HOSTNAME=$PUBLIC_URL|\" /etc/transferops/keycloak.env",
          "SMTP_PASSWORD=\"$(aws ssm get-parameter --region ${var.region} --name '/${local.name}/smtp-password' --with-decryption --query Parameter.Value --output text 2>/dev/null || true)\"",
          "printf 'KEYCLOAK_SMTP_PASSWORD=%s\\n' \"$SMTP_PASSWORD\" > /etc/transferops/keycloak-secret.env",
          "chmod 600 /etc/transferops/keycloak-secret.env",
          "systemctl restart keycloak",
          "systemctl is-active --quiet keycloak",
        ]
      }
    }]
  })
}

resource "aws_ssm_document" "warehouse_seed" {
  name            = "${local.name}-warehouse-seed"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Load the warehouse from the approved API image inside the private VPC"
    parameters = {
      ImageUri = { type = "String", allowedPattern = "^[0-9]+\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9/_-]+:[A-Za-z0-9._-]+$" }
      Operator = { type = "String", default = "", allowedPattern = "^$|^[A-Za-z0-9._@+-]{3,254}$" }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "seed"
      inputs = {
        timeoutSeconds = "1800"
        runCommand = [
          "set -euo pipefail",
          "IMAGE='{{ ImageUri }}'",
          "OPERATOR='{{ Operator }}'",
          "REGISTRY=\"$${IMAGE%%/*}\"",
          "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin \"$REGISTRY\"",
          "docker pull \"$IMAGE\"",
          "DSN=\"$(aws ssm get-parameter --region ${var.region} --name '/${local.name}/loader-dsn' --with-decryption --query Parameter.Value --output text)\"",
          "READER=\"$(aws ssm get-parameter --region ${var.region} --name '/${local.name}/db-reader-password' --with-decryption --query Parameter.Value --output text)\"",
          "AUDITOR=\"$(aws ssm get-parameter --region ${var.region} --name '/${local.name}/db-auditor-password' --with-decryption --query Parameter.Value --output text)\"",
          "AI=\"$(aws ssm get-parameter --region ${var.region} --name '/${local.name}/db-ai-password' --with-decryption --query Parameter.Value --output text)\"",
          "docker run --rm --network host --user root -e TRANSFEROPS_DSN=\"$DSN\" -e TRANSFEROPS_READER_PASSWORD=\"$READER\" -e TRANSFEROPS_AUDITOR_PASSWORD=\"$AUDITOR\" -e TRANSFEROPS_AI_PASSWORD=\"$AI\" -e TRANSFEROPS_OPERATOR=\"$OPERATOR\" \"$IMAGE\" sh -lc 'python etl/generate_data.py && python etl/run.py --engine postgres --dsn \"$TRANSFEROPS_DSN\" && python etl/grant_operator.py --dsn \"$TRANSFEROPS_DSN\"'",
        ]
      }
    }]
  })
}
