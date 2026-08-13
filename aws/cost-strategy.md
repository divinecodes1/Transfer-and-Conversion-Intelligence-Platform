# Cost Strategy — AWS Student Tier

**Which free tier you are on changes the bill from roughly zero to roughly
twenty dollars a month.** Everything below depends on that, so establish it
first:

```bash
aws freetier get-free-tier-usage --region us-east-1
# or: Billing console -> Free Tier
```

| Tier | What you get | This stack costs |
|---|---|---|
| **Legacy 12-month** | 750h/month RDS `t4g.micro`, 750h/month EC2 `t3.micro`, 30GB EBS, 5GB S3 | **~$0/month** |
| **Newer credit-based** | a credit balance, no free service-hours | **~$20/month**, dominated by RDS + EC2 |

The design assumes the worse case and minimises standing charges regardless.

---

## What each component costs

| Component | Tier | Idle cost |
|---|---|---|
| CloudFront + S3 (console) | always-free: 1TB out, 10M requests/month | **$0** |
| Lambda (API) | always-free: 1M requests + 400k GB-s/month | **~$0** |
| Lambda (nightly refresh) | runs for seconds, once a night | **~$0** |
| SSM Parameter Store | standard parameters | **$0** |
| ECR | 500MB free; lifecycle keeps 3 images | **~$0** |
| CloudWatch Logs | 5GB/month free, 14-day retention | **$0** |
| **EC2 t3.micro (Keycloak)** | **always on** | free 12mo, else ~$8 |
| **RDS db.t4g.micro** | **always on** | free 12mo, else ~$13 |
| NAT Gateway | **not provisioned** | would be ~$32 |

Two components run continuously and everything else is free or scales to zero.
That is the whole shape of the design.

---

## The three decisions that mattered most

### 1. Lambda instead of Fargate/App Runner

Fargate's floor is ~$9/month for 0.25 vCPU running 24/7, and it cannot scale to
zero. App Runner is ~$5–25/month with no free tier. Lambda is **$0 at demo
volume, forever** — not for twelve months.

The catch that usually kills this is the rewrite: handler signatures, Mangum,
splitting routes. The Lambda Web Adapter removes it entirely — the same
`uvicorn api.main:app`, unchanged.

### 2. No NAT Gateway

A NAT gateway is **~$32/month before it carries a byte** — more than the entire
rest of this stack. It exists to give private-subnet resources outbound
internet.

Avoided by putting the Keycloak host in a public subnet and running Lambda
outside the VPC. The cost is that RDS is reachable from the internet, protected
by credentials and TLS rather than by network isolation.
[security.md](security.md) states that plainly rather than implying otherwise.

### 3. SSM Parameter Store instead of Secrets Manager

$0 versus ~$2.80/month for seven secrets — nearly 10% of a $30 budget,
permanently, for automatic rotation that nothing here performs.

---

## Controls that are enforced, not documented

| Control | Where | What it does |
|---|---|---|
| Monthly budget + alerts at 50/75/90/100% | `budget.tf` | Email before the money is gone. AWS never hard-stops spending. |
| **Annual** budget | `budget.tf` | Catches slow burn. Twelve quiet months at $8 never trip a $30 *monthly* threshold and still drain a credit. |
| CloudWatch retention 14 days | `variables.tf` | The default is *never expire* — how log storage quietly becomes the largest line item. |
| ECR lifecycle, keep 3 | `main.tf` | 500MB free; images are ~400MB each. |
| S3 lifecycle rules | `site.tf` | Exports expire at 7 days, reports at 30, knowledge cools at 30. |
| `backup_retention_period = 1` | `database.tf` | The floor that still keeps backups. |
| No `multi_az`, no read replica | `database.tf` | Each doubles RDS permanently. |
| `performance_insights_enabled = false` | `database.tf` | Free window is only 7 days. |
| AI daily request cap | `TRANSFEROPS_AI_DAILY_CAP` | Ceiling on model calls per user per day. |
| `ai_provider = "mock"` default | `variables.tf` | No model spend at all unless deliberately switched on. |

**The budget is the one you must configure.** It is skipped entirely when
`budget_alert_emails` is empty:

```hcl
budget_alert_emails = ["you@university.edu"]
```

---

## Keeping the bill near zero

**Destroy it when you are not using it.** The single most effective control:

```bash
./scripts/destroy-aws-student.sh
```

It also checks for the things a `terraform destroy` misses — an **unattached
Elastic IP** and an **available EBS volume** both bill while doing nothing, and
neither appears as a "running" resource.

**Stop the two always-on pieces between demos:**

```bash
aws rds stop-db-instance --db-instance-identifier ti-student-db   # up to 7 days
aws ec2 stop-instances --instance-ids <keycloak-instance-id>
```

RDS compute stops billing; storage does not. It auto-starts after 7 days.

**Develop locally.** `docker compose up` plus DuckDB needs no AWS at all, and
the full test suite runs server-free.

---

## What will drain it fastest

Ranked by damage:

1. **NAT Gateway** — ~$32/month, more than everything else combined
2. **A larger RDS class** — `db.t3.small` is roughly double `t4g.micro`
3. **Multi-AZ RDS** — exactly double, permanently
4. **An ALB** — ~$16/month before traffic; the Function URL is free
5. **Unattached Elastic IPs** — ~$3.60/month each, invisible in most views
6. **Uncapped CloudWatch retention** — grows with a bug, not with usage
7. **ECS/EKS** — a control plane and nodes that cannot scale to zero
