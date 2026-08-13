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
variable "budget_time_grain" { type = string }

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

  amount = var.budget_amount

  # Monthly resets on the 1st and alarms on a bad month. Annually does not reset,
  # so it alarms on cumulative spend -- which is the one that matches how a
  # student credit actually runs out: twelve quiet months at 8 USD never trips a
  # monthly threshold and still empties a 100 USD credit.
  time_grain = var.budget_time_grain

  time_period {
    # The first of the CURRENT month, so the budget tracks spend from the moment
    # it is created. Azure requires a first-of-month start date.
    #
    # This previously added 720 hours to "now", which pushed the start into next
    # month -- the budget existed, showed green, and measured nothing during the
    # first month. That is precisely the month when a misconfigured resource is
    # most likely to be running, so the alert was absent exactly when it mattered.
    start_date = formatdate("YYYY-MM-01'T'00:00:00'Z'", timestamp())
  }

  # Four actual thresholds. 50 and 75 are the ones that leave time to turn
  # something off; by the time 100% is *actual*, the money is already spent.
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
