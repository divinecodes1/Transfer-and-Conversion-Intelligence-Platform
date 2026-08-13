# ============================================================================
# Budget.
#
# AWS does not stop spending when a budget is exceeded -- there is no hard cap
# on an account, and on a credit account the credit simply drains. The alert is
# the only early warning there is, which is why it is provisioned with the stack
# rather than left as a portal task nobody does.
#
# Two budgets are free per account, so this uses one and leaves room for a
# second (a cumulative one -- see the note below).
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

# A monthly budget alarms on a bad month. It does not alarm on slow, steady
# burn: twelve quiet months at 8 USD never trip a 30 USD monthly threshold and
# still empty a 100 USD credit.
#
# This second budget is annual and does not reset, so it tracks cumulative
# spend -- the failure mode that actually ends a student account.
resource "aws_budgets_budget" "annual" {
  count = length(var.budget_alert_emails) > 0 ? 1 : 0

  name         = "${local.name}-annual"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_amount * 4)
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

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
