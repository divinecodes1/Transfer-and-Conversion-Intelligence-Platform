# ============================================================================
# Network.
#
# One VPC, two public subnets, an internet gateway. No NAT gateway, no private
# subnets, no VPC endpoints -- and that absence is the single most important
# cost decision in this file.
#
# A NAT gateway is roughly 32 USD/month before it carries a byte. It exists to
# give resources in private subnets outbound internet access. Everything here
# that needs the internet (the Keycloak host pulling an image, the API reaching
# a model provider) sits in a public subnet with a public IP instead, which
# costs nothing.
#
# The consequence, stated plainly rather than implied: the database is reachable
# from the internet, protected by a security group, TLS and generated
# credentials rather than by network isolation. aws/security.md says so in as
# many words. The production fix is private subnets, a NAT or VPC endpoints, and
# a Lambda inside the VPC -- see aws/migration-to-enterprise.md.
#
# Two subnets, not one: RDS requires a subnet group spanning at least two
# availability zones even for a single-AZ instance.
# ============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---- Security groups --------------------------------------------------------

# Keycloak's host. Only 8080 from CloudFront-agnostic public traffic, because
# browsers hit it directly for sign-in.
resource "aws_security_group" "keycloak" {
  name        = "${local.name}-keycloak"
  description = "Keycloak identity provider"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Keycloak HTTP (browser sign-in and JWKS)"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # No SSH rule. Administration goes through SSM Session Manager, which needs no
  # open port, no key pair to lose, and records who connected. An open 22 on a
  # demo host is the most reliably scanned port on the internet.

  egress {
    description = "Pull the container image, reach the database, send mail"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-keycloak" }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Keycloak host"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.keycloak.id]
  }

  # The API runs on Lambda OUTSIDE the VPC -- deliberately, because putting it
  # inside would require a NAT gateway for it to reach the model provider and
  # Keycloak's public issuer URL. Lambda's source addresses are AWS-owned and
  # dynamic, so they cannot be allow-listed, which leaves this rule open.
  #
  # What actually protects the database: TLS is forced (see database.tf), the
  # master password is generated and never written to a file, and the API
  # connects as a least-privilege reader role that row-level security still
  # applies to. This is the same trade the Azure deployment made with its
  # "allow Azure services" rule, and it is documented rather than glossed.
  ingress {
    description = "Lambda API and the operator (see aws/security.md)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-database" }
}
