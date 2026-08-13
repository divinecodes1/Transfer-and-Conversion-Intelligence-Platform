# Resource group plus the budget that guards it.
#
# The two belong together: a resource group created without a budget is how a
# student subscription is discovered empty in March. Azure cannot hard-stop
# spend on a credit subscription, so the alert is the only mechanism there is --
# which makes it part of provisioning, not an afterthought in the portal.

variable "name" { type = string }
variable "location" { type = string }
variable "tags" { type = map(string) }
variable "budget_amount" { type = number }
variable "budget_contact_emails" { type = list(string) }

resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}

resource "azurerm_consumption_budget_resource_group" "this" {
  # No addresses, no budget: a budget with nowhere to send an alert is a row in
  # a portal nobody opens.
  count = length(var.budget_contact_emails) > 0 ? 1 : 0

  name              = "budget-${var.name}"
  resource_group_id = azurerm_resource_group.this.id

  amount     = var.budget_amount
  time_grain = "Monthly"

  time_period {
    # Budgets must start on the first of a month, and Azure rejects a start date
    # in the past on creation.
    start_date = formatdate("YYYY-MM-01'T'00:00:00'Z'", timeadd(timestamp(), "720h"))
  }

  # Four thresholds, three of them forecast-free actuals, because by the time
  # 100% is *actual* the money is already spent. 50 and 75 are the ones that
  # leave time to turn something off.
  dynamic "notification" {
    for_each = [50, 75, 90, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.budget_contact_emails
    }
  }

  # One forecast alert as well: it fires before the spend happens, which is the
  # only alert that can actually prevent anything.
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.budget_contact_emails
  }

  lifecycle {
    # start_date is computed from timestamp(), which changes on every plan and
    # would otherwise show a permanent diff.
    ignore_changes = [time_period]
  }
}

output "name" { value = azurerm_resource_group.this.name }
output "id" { value = azurerm_resource_group.this.id }
output "location" { value = azurerm_resource_group.this.location }
