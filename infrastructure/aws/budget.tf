# ============================================================================
# Budget.
#
# AWS does not stop spending when a budget is exceeded -- there is no hard cap
# on an account, and on a credit account the credit simply drains. The alert is
# the only early warning there is, which is why it is provisioned with the stack
# rather than left as a portal task nobody does.
#
# Monthly and calendar-year views expose both a sudden spike and slower burn.
# ============================================================================

resource "aws_budgets_budget" "monthly" {
  # No addresses, no budget: an alert with nowhere to go is a row in a console
  # nobody opens.
  count = length(var.budget_alert_emails) > 0 ? 1 : 0

  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_amount)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
  }

  # Actual thresholds. 50 and 75 are the ones that leave time to turn something
  # off; by the time 100% is actual, the money is already spent.
  dynamic "notification" {
    for_each = [50, 75, 90, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }

  # And one forecast alert, which is the only kind that can arrive before the
  # spend rather than after it.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }
}

# A monthly budget alarms on a bad month. The second view is calendar-year gross
# usage. The deployment script separately prints the authoritative remaining
# credits and expiration date, which is the cross-year Free Plan control.
resource "aws_budgets_budget" "annual" {
  count = length(var.budget_alert_emails) > 0 ? 1 : 0

  name         = "${local.name}-annual"
  budget_type  = "COST"
  limit_amount = tostring(var.free_plan_credit_budget_amount)
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

  cost_types {
    include_credit = false
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }
}
