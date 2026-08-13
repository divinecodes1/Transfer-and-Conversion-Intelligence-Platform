# Cost Strategy

The Azure for Students offer is **$100 of credit for 12 months**. It is a credit
subscription: when the credit runs out the subscription is disabled rather than
charged, which is a safety net and a deadline at the same time.

The target here is a stack that costs **near zero at idle** and spends the credit
only while it is being used.

---

## The test every resource had to pass

Before provisioning anything:

1. Is there a serverless option?
2. Can it scale to zero?
3. Is there a free grant?
4. Can the same job run on demand instead of continuously?
5. Can one shared resource serve two needs?
6. Do we need it continuously, or only during a demo?

Where the answer suggested unnecessary cost, the design changed rather than the
budget.

---

## What each component costs

| Component | Tier | Idle cost | Notes |
|---|---|---|---|
| Static Web Apps | Free | **0** | 100 GB/month bandwidth, managed TLS |
| Container App — API | Consumption, min=0 | **~0** | inside the monthly free grant at demo volume |
| Container App — Keycloak | Consumption, min=0 | **~0** | 40–60s cold start on first sign-in |
| Container Apps Job | cron, on demand | **~0** | runs for seconds, once a night |
| PostgreSQL Flexible Server | B_Standard_B1ms, 32 GB | **the one standing charge** | free for 12 months on an eligible subscription; otherwise roughly 12–15 USD/month |
| Blob Storage | Standard_LRS, hot | **~0** | inside the free grant; lifecycle rules expire exports |
| Log Analytics + App Insights | PerGB2018, capped 0.1 GB/day | **0** | inside the 5 GB/month free grant |
| Key Vault | Standard | **~0** | per-10,000-operations billing, rounds to nothing |
| Container Registry | *not provisioned* | **0** | GHCR instead — ACR Basic is a fixed ~5 USD/month |

**Realistic monthly total: 0–15 USD**, dominated entirely by PostgreSQL. If the
free database offer applies, an idle month approaches zero.

---

## The three decisions that mattered most

### 1. `min_replicas = 0` on both Container Apps

This is the whole cost model. A container held warm bills for every second it
exists, whether or not anyone is using it.

The Keycloak case makes the size of it concrete. At 0.5 vCPU and 1 GiB held
continuously:

```
0.5 vCPU × 2.6M seconds/month  = 1.30M vCPU-seconds
                free grant     = 0.18M
                    billable   = 1.12M  ≈ 27 USD

1 GiB × 2.6M seconds/month     = 2.60M GiB-seconds
                free grant     = 0.36M
                    billable   = 2.24M  ≈  7 USD
                                        ─────────
                                        ≈ 34 USD/month
```

**A third of the entire student credit, every month, to validate tokens for a
demo nobody is signed in to.** At zero it costs essentially nothing and the price
becomes a 40–60 second wait on the first sign-in.

Set `keycloak_min_replicas = 1` for the duration of a live demonstration, then
set it back.

### 2. GitHub Container Registry instead of ACR

ACR Basic is roughly **5 USD/month, fixed**, whether or not you push anything —
5% of the credit per month for storage GHCR provides free for public images.
Container Apps pulls public images with no credential at all.

`use_acr = true` provisions ACR with managed-identity `AcrPull` when images must
stay private inside Azure.

### 3. One database server, two databases

Flexible Server bills per **server**. Running Keycloak on its own instance would
double the single largest standing charge in the stack, to gain isolation that
separate databases and separate credentials already provide at this scale.

---

## Controls that are enforced, not documented

| Control | Where | What it actually does |
|---|---|---|
| Budget + alerts at 50/75/90/100% | `modules/resource-group` | Email before the credit is gone. Azure cannot hard-stop a credit subscription, so this is the only early warning. |
| Log ingestion cap 0.1 GB/day | `modules/monitoring` | **Hard cap.** Ingestion stops for the day; a logging loop cannot run up a bill overnight. |
| Blob lifecycle rules | `modules/storage` | Exports expire after 7 days, generated reports after 30, knowledge cools after 30. |
| Backup retention at the 7-day floor | `modules/database` | Retained backups bill beyond the free allowance. |
| `geo_redundant_backup_enabled = false` | `modules/database` | Would double backup cost for synthetic data. |
| No `high_availability` block | `modules/database` | HA provisions a second server and bills for it — exactly double, permanently. |
| AI daily request cap | `TRANSFEROPS_AI_DAILY_CAP` | Ceiling on model calls per user per day, enforced in the app. |
| AI response caching | `tr_ai` | A repeated question against an unchanged vintage is served from the warehouse, not the provider. |
| `ai_provider = "mock"` default | `variables.tf` | The demo has no model spend at all unless it is deliberately switched on. |

**The budget is the one you must configure.** It is skipped entirely when
`budget_alert_emails` is empty, because an alert with nowhere to go is a row in
a portal nobody opens:

```hcl
budget_alert_emails = ["you@university.edu"]
```

---

## Keeping the bill near zero

**Destroy it when you are not using it.** The single most effective control:

```bash
./scripts/destroy-azure-student.sh
```

Everything rebuilds from this repository in a few minutes. Nothing in the running
system is precious — the warehouse regenerates from `sql/` and the generator, and
the realm re-imports.

**Develop locally.** `docker compose up` plus DuckDB needs no Azure at all. The
full test suite runs server-free. Azure is for demonstrating, not for iterating.

**Check what is actually running:**

```bash
az resource list --output table
az consumption budget list --output table
```

---

## Where the money goes if you are not careful

Ranked by how much damage each does on a $100 credit:

1. **AKS** — a control plane plus nodes that cannot scale to zero. Would consume
   the entire credit in weeks.
2. **`min_replicas = 1` on Keycloak** — ~34 USD/month, mostly idle.
3. **Application Gateway / Front Door / Firewall** — each a standing hourly
   charge before a single request.
4. **Premium Redis** — for a cache the database already provides.
5. **A larger database SKU** — B2s is roughly four times B1ms for a dataset that
   fits in RAM.
6. **Uncapped Log Analytics** — the one that surprises people, because it grows
   with a bug rather than with usage.
7. **ACR Basic** — small, but fixed and permanent, and avoidable.
