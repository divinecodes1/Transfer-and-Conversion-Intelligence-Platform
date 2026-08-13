# ============================================================================
# RDS PostgreSQL.
#
# The one standing charge in the stack. db.t4g.micro is 750h/month free on the
# legacy tier and roughly 12-13 USD/month otherwise, which is why every other
# component was chosen to scale to zero or sit in an always-free tier: this is
# the number the budget has to absorb.
#
# Sizing: the warehouse is ~260 projects with full schedule history, a few
# hundred thousand rows, working set in memory. The bottleneck in this platform
# has never been the database.
#
# No Multi-AZ, no read replica, no Performance Insights beyond the free window.
# Each roughly doubles a cost to protect synthetic data that rebuilds from sql/
# in about a minute.
# ============================================================================

resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.public[*].id
}

# pgvector and forced TLS. Both are parameter-group settings, so they are part
# of the infrastructure rather than something run by hand after provisioning.
resource "aws_db_parameter_group" "main" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  # Without this, libpq will happily negotiate plaintext -- and this database is
  # reachable from the internet, so the traffic would cross it unencrypted.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # Available to CREATE EXTENSION once allow-listed here. The retrieval layer
  # uses pgvector, and a dedicated vector database would be a standing charge
  # for a capability this instance already has.
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  # gp3 is the current generation and is not more expensive than gp2 at this
  # size. No autoscaling: storage can grow but never shrink, so an accidental
  # expansion is a permanent charge.
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "transferops"
  username = var.db_username
  password = random_password.db_master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.main.name

  # Public, because the API runs on Lambda outside the VPC. See the long comment
  # on the database security group in network.tf, and aws/security.md.
  publicly_accessible = true

  multi_az                = false
  backup_retention_period = 1 # 0 disables automated backups entirely; 1 is the floor that keeps them
  skip_final_snapshot     = true
  deletion_protection     = false # a demo must be destroyable in one command
  apply_immediately       = true

  # Minor versions land in a predictable window rather than whenever AWS
  # chooses; major upgrades stay manual.
  auto_minor_version_upgrade  = true
  maintenance_window          = "Sun:03:00-Sun:04:00"
  backup_window               = "02:00-03:00"
  performance_insights_enabled = false # the free window is 7 days; off is simpler and certainly free

  tags = { Name = "${local.name}-db" }
}

locals {
  db_host = aws_db_instance.main.address

  # Assembled once and stored whole. A connection string cannot be composed at
  # runtime from a separate password parameter without putting the password in a
  # plain environment variable, where it would show up in the Lambda console and
  # in any log that dumps the environment.
  #
  # sslmode=require is not decoration: this database is on public networking.
  dsn = {
    admin   = "postgresql://${var.db_username}:${urlencode(random_password.db_master.result)}@${local.db_host}:5432/transferops?sslmode=require"
    reader  = "postgresql://transferops_reader:${urlencode(random_password.db_reader.result)}@${local.db_host}:5432/transferops?sslmode=require"
    auditor = "postgresql://transferops_auditor:${urlencode(random_password.db_auditor.result)}@${local.db_host}:5432/transferops?sslmode=require"
    ai      = "postgresql://transferops_ai:${urlencode(random_password.db_ai.result)}@${local.db_host}:5432/transferops?sslmode=require"
  }

  # Keycloak takes a JDBC URL and separate credentials, and gets its own database
  # on the same instance. A second instance would double the largest standing
  # charge to gain isolation that a separate database and separate credentials
  # already provide at this scale.
  keycloak_jdbc_url = "jdbc:postgresql://${local.db_host}:5432/keycloak?sslmode=require"
}

# The operator's own address, so `python etl/run.py` works from the laptop that
# runs the deploy script. Separate from the open rule above so that tightening
# that rule later does not also lock out the loader.
resource "aws_vpc_security_group_ingress_rule" "operator_postgres" {
  count = var.allowed_client_ip == "" ? 0 : 1

  security_group_id = aws_security_group.database.id
  description       = "Operator laptop"
  cidr_ipv4         = var.allowed_client_ip
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
}
