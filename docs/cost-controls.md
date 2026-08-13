# Cost controls — operator guide

The current AWS Free Plan is credit-based. Check its authoritative state before
each deployment:

```powershell
aws freetier get-account-plan-state --region us-east-1 --output table
```

The deployment scripts perform this check and refuse an inactive/non-Free plan
unless `TRANSFEROPS_ALLOW_PAID=true` is explicitly set.

Set `monthly_budget_amount`, `free_plan_credit_budget_amount`,
`free_plan_expiration_date` and `budget_alert_emails` in `terraform.tfvars`.
The budgets exclude credits from their calculations, showing gross usage rather
than a misleading near-zero net bill. AWS alerts do not stop spending.

The only always-on compute is a micro RDS instance and one micro EC2 instance.
The EC2 host runs Keycloak and NAT for private Lambda egress. AWS also charges
the single public IPv4 address. Lambda, S3 and CloudFront remain usage-based.

Check month-to-date cost in Cost Explorer and inspect project-tagged resources:

```powershell
aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=transfer-intelligence
terraform -chdir=infrastructure/aws output -raw cost_posture
```

Stopping the EC2 host also stops Keycloak and private Lambda internet egress.
Stopping RDS stops compute billing but not storage and AWS automatically starts
it after seven days. For longer idle periods, destroy the reproducible stack:

```powershell
.\scripts\destroy-aws-student.ps1
```

The script destroys the application state first and ECR bootstrap second. Also
review unattached public IPv4 addresses, available EBS volumes, manual RDS
snapshots, old ECR images and CloudWatch ingestion—these can bill without a
running application.

Avoid NAT Gateway, ALB, Multi-AZ RDS, ECS/EKS, additional regions and unmanaged
log/image retention on this student account. See
[aws/cost-strategy.md](../aws/cost-strategy.md) for the architecture choices.
