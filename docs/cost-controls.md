# Cost Controls — Operator Guide

Practical guide to keeping the AWS demo near zero. The reasoning is in
[aws/cost-strategy.md](../aws/cost-strategy.md); this is what to *do*.

---

## Do these first

### 1. Find out which free tier you have

The single biggest cost fact, and it is not obvious in the console:

```bash
aws freetier get-free-tier-usage --region us-east-1
```

| Result | Meaning |
|---|---|
| Usage records returned | **Legacy 12-month tier** — RDS and EC2 free for 750h/month. This stack costs ~$0. |
| Empty / not available | Likely the **credit-based tier** — no free service hours. Expect ~$20/month. |

### 2. Set the budget

Skipped entirely when `budget_alert_emails` is empty, and **AWS never stops
spending on its own**:

```hcl
monthly_budget_amount = 30
budget_alert_emails   = ["you@university.edu"]
```

You get two budgets — monthly (a bad month) and annual (slow burn). The second
matters: twelve quiet months at $8 never trip a $30 *monthly* threshold and
still drain a credit.

### 3. Destroy it when you are not using it

```bash
./scripts/destroy-aws-student.sh
```

The single most effective control. Everything rebuilds from this repository.

---

## Checking what you are spending

```bash
# Month to date, by service
aws ce get-cost-and-usage --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE --region us-east-1

# Everything this project created
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=project,Values=transfer-intelligence

# The two things that always bill
aws rds describe-db-instances --query "DBInstances[].{id:DBInstanceIdentifier,status:DBInstanceStatus}" -o table
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].{id:InstanceId,type:InstanceType}" -o table
```

---

## The knobs, by impact

### Stop the two always-on components between demos

These are the only components that bill continuously:

```bash
# RDS — compute stops billing, storage does not. Auto-starts after 7 days.
aws rds stop-db-instance --db-instance-identifier ti-student-db

# Keycloak
aws ec2 stop-instances --instance-ids $(terraform -chdir=infrastructure/aws output -raw keycloak_instance_id)
```

Restart before a demo:

```bash
aws rds start-db-instance --db-instance-identifier ti-student-db
aws ec2 start-instances --instance-ids <id>
```

> The Elastic IP stays attached to a **stopped** instance, so the Keycloak URL
> survives. An Elastic IP attached to nothing bills ~$3.60/month.

### Everything else needs no attention

Lambda scales to zero, CloudFront and S3 sit inside the always-free tier, and
the nightly job runs for seconds. There is nothing to turn off.

---

## Things that quietly bill

The ones that do not appear in any "running resources" view:

| Thing | Cost | Find it |
|---|---|---|
| **Unattached Elastic IP** | ~$3.60/mo | `aws ec2 describe-addresses --query "Addresses[?AssociationId==null]"` |
| **Available EBS volume** | ~$0.08/GB/mo | `aws ec2 describe-volumes --filters Name=status,Values=available` |
| **Manual RDS snapshots** | storage rate | `aws rds describe-db-snapshots --snapshot-type manual` |
| **Old ECR images** | $0.10/GB/mo | lifecycle policy keeps 3 |
| **CloudWatch log groups** | $0.50/GB ingest | retention is 14 days |

`destroy-aws-student.sh` checks all of these after tearing down — the reason it
exists rather than a bare `terraform destroy`.

---

## Developing without spending

AWS is for demonstrating, not iterating.

```bash
docker compose up -d          # PostgreSQL + Keycloak + Mailpit
python etl/run.py --engine duckdb
make test                     # every server-free suite
make api && make web
```

The full suite runs against DuckDB with no server at all, and
`TRANSFEROPS_AI_PROVIDER=mock` means no model spend either.

---

## What will drain it fastest

| Do not | Why |
|---|---|
| Add a **NAT Gateway** | ~$32/month — more than the entire rest of the stack |
| Add an **ALB** | ~$16/month before a single request |
| Enable **Multi-AZ RDS** | exactly double, permanently |
| Raise the **RDS class** | `db.t3.small` is roughly double `t4g.micro` |
| Deploy **ECS/EKS** | a control plane and nodes that cannot scale to zero |
| Use **Secrets Manager** | $0.40/secret/month for rotation nothing here does |
| Leave an **Elastic IP unattached** | invisible, permanent |
| Deploy to a **second region** | doubles everything, plus inter-region transfer |

---

## If the free tier ends or the credit runs out

The account is not disabled the way an Azure credit subscription is — **AWS
starts charging your payment method**. That is a more dangerous failure mode,
and it is why the budget alerts matter more here than they did on Azure.

If you are not actively demonstrating: destroy the stack. It rebuilds in about
fifteen minutes, and nothing in the running system is precious.

---

## Monthly checklist

- [ ] Budget alerts still going to an address you read
- [ ] `cost_posture` output shows nothing unexpected
- [ ] RDS and EC2 stopped if unused for days
- [ ] No unattached Elastic IPs, no available EBS volumes
- [ ] No manual RDS snapshots you forgot about
- [ ] Cost Explorer month-to-date matches expectation
