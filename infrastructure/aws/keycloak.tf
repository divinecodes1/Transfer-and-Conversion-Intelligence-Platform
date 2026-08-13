# ============================================================================
# Keycloak, on one small EC2 instance.
#
# This is where AWS beats the previous Azure design outright, and it is worth
# being explicit about why.
#
# Keycloak is a stateful JVM. It cannot scale to zero without dropping sessions,
# and it takes 40-60 seconds to cold start. On Azure Container Apps that left
# two bad options: hold a replica warm for roughly 34 USD/month -- a third of
# the student credit, spent almost entirely on idle time -- or make every first
# sign-in of the day wait a minute.
#
# A t4g.micro is 750 hours a month free on the legacy tier, which is more hours
# than a month contains. It simply runs. Always warm, no cold start, and on the
# free tier no bill. Off the free tier it is about 6 USD/month, still a sixth of
# the Azure figure.
#
# The instance runs the same image the Azure deployment used -- realm and themes
# baked in -- because EC2 has no bind mount from a laptop either.
# ============================================================================

# x86_64, not Graviton -- and the reason is CI, not the instance.
#
# t4g is Graviton (arm64) and about 10% cheaper. But GitHub's hosted runners are
# x86, so every image build for an arm64 target would run under QEMU emulation:
# minutes instead of seconds, and a class of "works locally, fails in CI" bugs
# that have nothing to do with this application.
#
# t3.micro is also 750h/month on the legacy free tier, so on the tier that
# matters here the two cost exactly the same: nothing. The 10% only appears
# after the free tier ends, and it is not worth an emulated build pipeline.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

# ---- Instance role ----------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "keycloak" {
  name               = "${local.name}-keycloak"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Session Manager instead of SSH. No open port 22, no key pair to lose, and a
# record of who connected. The security group has no SSH rule at all.
resource "aws_iam_role_policy_attachment" "keycloak_ssm" {
  role       = aws_iam_role.keycloak.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Pull the image from ECR. Read-only, and only from this account's registry.
resource "aws_iam_role_policy_attachment" "keycloak_ecr" {
  role       = aws_iam_role.keycloak.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Read its own configuration from SSM. Scoped to this deployment's prefix, so
# the host cannot read another stack's parameters.
data "aws_iam_policy_document" "keycloak_ssm_read" {
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${local.name}/*"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "keycloak_ssm_read" {
  name   = "${local.name}-keycloak-ssm"
  role   = aws_iam_role.keycloak.id
  policy = data.aws_iam_policy_document.keycloak_ssm_read.json
}

resource "aws_iam_instance_profile" "keycloak" {
  name = "${local.name}-keycloak"
  role = aws_iam_role.keycloak.name
}

# ---- A stable address -------------------------------------------------------
# An Elastic IP is free while attached to a running instance, and it is what
# keeps the realm's issuer URL constant across a stop/start. Without it the
# public IP changes, every previously issued token fails issuer validation, and
# the console's Keycloak URL has to be rebuilt.
resource "aws_eip" "keycloak" {
  domain = "vpc"
  tags   = { Name = "${local.name}-keycloak" }
}

resource "aws_eip_association" "keycloak" {
  instance_id   = aws_instance.keycloak.id
  allocation_id = aws_eip.keycloak.id
}

# ---- The host ---------------------------------------------------------------

resource "aws_instance" "keycloak" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.keycloak_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.keycloak.id]
  iam_instance_profile   = aws_iam_instance_profile.keycloak.name
  key_name               = var.ssh_public_key == "" ? null : aws_key_pair.keycloak[0].key_name

  root_block_device {
    volume_size = var.keycloak_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only; IMDSv1 is how instance credentials get stolen through SSRF
  }

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/keycloak-user-data.sh.tftpl", {
    region         = var.region
    registry       = split("/", aws_ecr_repository.keycloak.repository_url)[0]
    image          = "${aws_ecr_repository.keycloak.repository_url}:latest"
    parameter_path = "/${local.name}"
    jdbc_url       = local.keycloak_jdbc_url
    db_username    = var.db_username
    admin_username = "kcadmin"
    web_origin     = "https://${aws_cloudfront_distribution.console.domain_name}"
    public_ip      = aws_eip.keycloak.public_ip
  })

  tags = { Name = "${local.name}-keycloak" }

  depends_on = [aws_db_instance.main]
}

resource "aws_key_pair" "keycloak" {
  count = var.ssh_public_key == "" ? 0 : 1

  key_name   = "${local.name}-keycloak"
  public_key = var.ssh_public_key
}
