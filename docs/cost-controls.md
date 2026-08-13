# Cost Controls — Operator Guide

Practical guide to keeping the Azure demo inside a $100 student credit. The
reasoning behind the design is in
[azure/cost-strategy.md](../azure/cost-strategy.md); this is what to *do*.

---

## Do these first

### 1. Set the budget

Without `budget_alert_emails`, no budget is created at all — an alert with
nowhere to go is a row in a portal nobody opens.

```hcl
monthly_budget_amount = 30
budget_time_grain     = "Monthly"
budget_alert_emails   = ["you@university.edu"]
```

Alerts fire at 50%, 75%, 90% and 100% of the amount — so a budget of 30 warns at
**15, 22.50, 27 and 30** — plus one **forecast** alert, the only one that
arrives before the money is spent.

**Pick the grain deliberately**, because the two answer different questions:

| Grain | Alarms when | Catches |
|---|---|---|
| `Monthly` | one month exceeds the amount | a runaway resource, a replica left warm |
| `Annually` | *cumulative* spend exceeds it | slow, steady credit burn |

Monthly is the default and the operational alarm. But note the gap it leaves:
this stack should cost 0–15 USD/month, so twelve quiet months at 8 USD never
trip a 30 USD monthly threshold and still empty a 100 USD credit. If what you
want is "tell me when I have used 30 of my 100", set
`budget_time_grain = "Annually"`.

Nothing stops you running both — Azure allows multiple budgets on a resource
group.

> Azure cannot hard-stop spend on a credit subscription. The alert is the
> mechanism, not a cap.

### 2. Confirm nothing is pinned warm

```bash
terraform output -raw cost_posture
```

Anything reading `BILLS CONTINUOUSLY` is costing money right now.

### 3. Destroy when you are done

```bash
./scripts/destroy-azure-student.sh
```

The single most effective control. Everything rebuilds from this repository.

---

## Checking what you are spending

```bash
# Current burn
az consumption usage list --top 20 --output table

# Remaining credit — portal only
# Cost Management + Billing → Credits

# What exists right now
az resource list --output table

# Container Apps replicas (the thing most likely to be left warm)
az containerapp list --query "[].{name:name, min:properties.template.scale.minReplicas}" -o table
```

---

## The knobs, by impact

### Keycloak replicas — the big one

```bash
# Before a demo: hold it warm, no cold start
az containerapp update --name ti-auth-student \
  --resource-group rg-transfer-intelligence-student --min-replicas 1

# After: back to zero
az containerapp update --name ti-auth-student \
  --resource-group rg-transfer-intelligence-student --min-replicas 0
```

**Left at 1, this is roughly 30–35 USD/month** — a third of the credit, spent
almost entirely on idle time. Set it back.

### API replicas

```bash
az containerapp update --name ti-api-student \
  --resource-group rg-transfer-intelligence-student --min-replicas 0
```

The API cold-starts in seconds, not a minute, so there is rarely a reason to pin
it.

### Stop the database overnight

The one standing charge. Flexible Server can be stopped for up to 7 days:

```bash
az postgres flexible-server stop  --name ti-db-student --resource-group rg-transfer-intelligence-student
az postgres flexible-server start --name ti-db-student --resource-group rg-transfer-intelligence-student
```

Compute stops billing; storage does not. It auto-starts after 7 days.

### Log ingestion

Already capped at 0.1 GB/day — a **hard** cap. To check:

```bash
az monitor log-analytics workspace show --name ti-logs-student \
  --resource-group rg-transfer-intelligence-student --query workspaceCapping
```

---

## Developing without spending

Azure is for demonstrating, not iterating.

```bash
docker compose up -d          # PostgreSQL + Keycloak + Mailpit
python etl/run.py --engine duckdb
make test                     # every server-free suite
make api && make web
```

The full suite runs against DuckDB with no server at all. `TRANSFEROPS_AI_PROVIDER=mock`
means no model spend locally either.

---

## Things that will drain the credit

| Do not | Why |
|---|---|
| Provision AKS | control plane + nodes that cannot scale to zero — weeks, not months |
| Leave `min_replicas = 1` on Keycloak | ~34 USD/month, mostly idle |
| Add Front Door / App Gateway / Firewall | standing hourly charge before a single request |
| Provision Premium Redis | for a cache `tr_ai` already provides |
| Raise the database SKU | B2s ≈ 4× B1ms for a dataset that fits in RAM |
| Enable HA on the database | provisions a second server — exactly double, permanently |
| Uncap Log Analytics | grows with a bug, not with usage |
| Provision ACR "just in case" | fixed ~5 USD/month; GHCR is free |
| Deploy to a second region | doubles everything, plus egress |

---

## If the credit runs out

The subscription is **disabled**, not charged. Resources stop and are eventually
deleted.

To recover: renew the student offer if still eligible, or upgrade to
pay-as-you-go — then `./scripts/deploy-azure-student.sh` rebuilds everything.

Nothing in the running system is precious. The warehouse regenerates from `sql/`
and the generator; the realm re-imports; the infrastructure is in Terraform.
That is what makes destroying it a routine act rather than a loss.

---

## Monthly checklist

- [ ] Budget alerts still going to an address you read
- [ ] `cost_posture` shows nothing billing continuously
- [ ] `az resource list` shows only expected resources
- [ ] Database stopped if unused for days
- [ ] No stray resource groups from experiments
- [ ] Credit remaining still matches the plan
