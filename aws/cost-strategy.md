# AWS Free Plan cost controls

New AWS accounts use the six-month credit Free Plan. Detect the authoritative
account state with:

```bash
aws freetier get-account-plan-state --region us-east-1
```

Terraform creates monthly and annual gross-cost budgets when alert emails are
provided. `include_credit = false` ensures promotional credits do not hide the
rate at which resources consume the balance. AWS Budgets alert; they do not stop
resources automatically.

Standing-cost controls in this stack:

- one small EC2 instance serves Keycloak and NAT duties;
- one private single-AZ RDS micro instance with 20 GB gp3;
- one paid public IPv4 address (AWS currently charges $0.005/hour);
- no NAT Gateway, ALB, Route53 zone, custom certificate, ECS/EKS or cache;
- Lambda API, assistant and refresh scale to zero;
- ECR retains only three images per repository;
- CloudWatch logs expire after 14 days;
- generated S3 exports expire automatically;
- SSM standard parameters replace per-secret Secrets Manager charges.

Set `free_plan_expiration_date` and alert amounts in `terraform.tfvars`. Use the
destroy script when the demo is not needed; it deletes application resources
before the separate ECR bootstrap state.
