# Log Analytics + Application Insights.
#
# Observability is the component most likely to quietly become the largest line
# on a student invoice, because ingestion is billed per GB and a chatty service
# under a retry loop can produce gigabytes in an afternoon. Two controls make
# that impossible rather than unlikely:
#
#   * daily_quota_gb is a HARD cap -- ingestion stops for the day when it is
#     reached. Losing an afternoon of demo logs is an acceptable failure mode;
#     losing the subscription is not.
#   * retention sits at the 30-day floor, which is inside the free allowance.
#
# The application already helps: observability/logs.py emits structured JSON with
# the route template rather than the resolved path, so cardinality stays flat.

variable "workspace_name" { type = string }
variable "app_insights_name" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }
variable "retention_in_days" { type = number }
variable "daily_quota_gb" { type = number }

resource "azurerm_log_analytics_workspace" "this" {
  name                = var.workspace_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = var.app_insights_name
  resource_group_name = var.resource_group_name
  location            = var.location
  application_type    = "web"

  # Workspace-based rather than classic: classic Application Insights is retired,
  # and the workspace is where the daily cap above actually applies.
  workspace_id = azurerm_log_analytics_workspace.this.id

  # Sampling at the source. At demo volume everything is captured anyway; the
  # setting matters the day something starts looping.
  sampling_percentage = 100
  tags                = var.tags
}

output "workspace_id" { value = azurerm_log_analytics_workspace.this.id }
output "workspace_customer_id" { value = azurerm_log_analytics_workspace.this.workspace_id }
output "connection_string" {
  value     = azurerm_application_insights.this.connection_string
  sensitive = true
}
output "instrumentation_key" {
  value     = azurerm_application_insights.this.instrumentation_key
  sensitive = true
}
