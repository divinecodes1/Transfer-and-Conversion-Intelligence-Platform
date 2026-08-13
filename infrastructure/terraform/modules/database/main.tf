# PostgreSQL Flexible Server, smallest burstable tier.
#
# Sizing rationale: the warehouse is ~260 projects with full schedule history --
# a few hundred thousand rows. B1ms (1 vCore burstable, 2 GiB) holds the working
# set in memory. The bottleneck in this platform has never been the database.
#
# Public networking with firewall rules rather than a private endpoint + VNet.
# That is a deliberate student-tier decision and it is a real trade: a private
# endpoint is roughly the cost of the database again, plus a VNet, plus the
# Container Apps environment has to be VNet-injected, which forfeits the
# scale-to-zero Consumption profile. The compensating controls are TLS-only,
# a closed default firewall, and least-privilege roles created by the loader.
# azure/security.md states this plainly rather than implying the demo is
# production-networked.
#
# pgvector is enabled here because the retrieval layer uses it and the
# alternative -- a dedicated vector database -- is a standing charge for a
# capability this server already has.

variable "server_name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }
variable "sku_name" { type = string }
variable "storage_mb" { type = number }
variable "backup_retention_days" { type = number }
variable "administrator_login" { type = string }
variable "administrator_password" {
  type      = string
  sensitive = true
}
variable "allowed_client_ip" { type = string }

resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.server_name
  resource_group_name = var.resource_group_name
  location            = var.location

  version    = "16"
  sku_name   = var.sku_name
  storage_mb = var.storage_mb

  administrator_login    = var.administrator_login
  administrator_password = var.administrator_password

  backup_retention_days        = var.backup_retention_days
  geo_redundant_backup_enabled = false # doubles backup cost for a synthetic dataset

  # No high_availability block at all. HA on Flexible Server provisions a second
  # standby server and bills for it -- exactly double, permanently, to protect
  # a demo from an outage nobody is paged for.

  public_network_access_enabled = true
  zone                          = "1"

  tags = var.tags

  lifecycle {
    # Azure picks an availability zone if one is not pinned, and a later plan
    # would otherwise propose destroying and recreating the server to move it.
    ignore_changes = [zone, high_availability]
  }
}

resource "azurerm_postgresql_flexible_server_database" "transferops" {
  name      = "transferops"
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"

  lifecycle {
    prevent_destroy = false
  }
}

# Keycloak's own store, on the same server.
#
# A second database rather than a second server: Flexible Server bills per
# server, so co-tenanting costs nothing while a dedicated instance would double
# the largest standing charge in the stack. The isolation that matters -- separate
# schemas, separate credentials, no shared tables -- is preserved. Splitting them
# is a production decision, and it is the first thing
# azure/migration-to-enterprise.md separates.
resource "azurerm_postgresql_flexible_server_database" "keycloak" {
  name      = "keycloak"
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"

  lifecycle {
    prevent_destroy = false
  }
}

# pgvector and pg_stat_statements, enabled at the server level. Extensions must
# be allow-listed here before CREATE EXTENSION succeeds inside the database.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "VECTOR,PG_STAT_STATEMENTS"
}

# TLS is not optional. The default already requires it; stating it means a later
# "just for a minute" relaxation shows up as an infrastructure diff in review.
resource "azurerm_postgresql_flexible_server_configuration" "require_ssl" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "ON"
}

# Container Apps egresses from shared Azure address space, so the app reaches
# the server through this rule. It is broad -- any Azure service can attempt a
# connection -- which is why it is paired with strong credentials and
# least-privilege roles rather than treated as a boundary on its own.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# The operator's own address, so `python etl/run.py --engine postgres` works
# from the laptop that runs the deploy script. Omitted when no IP is supplied.
resource "azurerm_postgresql_flexible_server_firewall_rule" "client" {
  count = var.allowed_client_ip == "" ? 0 : 1

  name             = "allow-operator"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = var.allowed_client_ip
  end_ip_address   = var.allowed_client_ip
}

output "fqdn" { value = azurerm_postgresql_flexible_server.this.fqdn }
output "server_id" { value = azurerm_postgresql_flexible_server.this.id }
output "database_name" { value = azurerm_postgresql_flexible_server_database.transferops.name }
output "keycloak_database_name" { value = azurerm_postgresql_flexible_server_database.keycloak.name }
