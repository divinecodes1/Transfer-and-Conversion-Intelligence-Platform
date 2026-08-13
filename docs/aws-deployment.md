# AWS Free Plan deployment

The AWS path is fully scripted for Bash and Windows PowerShell. It uses the
AWS-owned `cloudfront.net` hostnames, so no domain or ACM certificate is needed.

## Prerequisites

- AWS CLI v2, Terraform 1.6+, Docker Desktop, Node 22 and npm
- an authenticated AWS CLI session (`aws configure` or `aws sso login`)
- Docker Desktop running
- a budget notification email in `infrastructure/aws/terraform.tfvars`

Check the account using the current API:

```powershell
aws freetier get-account-plan-state --region us-east-1 --output table
```

New accounts use the six-month credit Free Plan. Service usage consumes the
credit balance; credits do not make the underlying resources free. The
Terraform budgets deliberately exclude credits from their calculation so the
gross burn rate remains visible.

## Configure

```powershell
Copy-Item infrastructure/aws/terraform.tfvars.example infrastructure/aws/terraform.tfvars
notepad infrastructure/aws/terraform.tfvars
```

Two settings in that file decide whether CI can deploy at all:

```hcl
github_repository = "owner/name"   # creates the OIDC provider and the CI role
budget_alert_emails = ["you@example.com"]   # empty disables the budget entirely
```

Never put passwords or API keys in the tfvars file. Set secrets in the current
PowerShell session:

```powershell
$env:TF_VAR_ai_api_key = "your-rotated-model-key"
$env:TF_VAR_smtp_password = "your-smtp-app-password"
$env:TRANSFEROPS_OPERATOR = "your-login-email@example.com"
```

SMTP works without a domain. A dedicated Gmail account with 2FA and an App
Password is the simplest test relay. Amazon SES also works, but while its
account is in the sandbox both sender and recipient addresses must be verified.
Set `smtp_host`, `smtp_from`, `smtp_reply_to`, `smtp_username`, TLS and port in
the tfvars file. Keycloak then sends registration verification and password
recovery mail.

## Deploy

PowerShell:

```powershell
.\scripts\deploy-aws-student.ps1
```

Bash:

```bash
./scripts/deploy-aws-student.sh
```

The workflow is two-stage by design:

1. `infrastructure/aws/bootstrap` creates ECR repositories in its own state.
2. Images are built and pushed.
3. `infrastructure/aws` creates Lambda, private RDS, EC2, CloudFront and SSM.
4. A constrained SSM document sets the HTTPS Keycloak hostname and rolls it.
5. Another constrained document loads RDS from inside the VPC and grants the
   initial operator.
6. The console is built with API, assistant and Keycloak HTTPS URLs and uploaded.

This ordering fixes the first-deploy problem where Lambda rejects an image URI
whose repository or image does not exist yet.

## Network and ingress

- RDS has no public address. Only the API/refresh Lambda security group and
  Keycloak security group can connect on PostgreSQL port 5432.
- API and refresh run in private subnets.
- The Keycloak EC2 host performs NAT for those private functions, avoiding the
  fixed NAT Gateway hourly charge. This is a cost-optimized single-instance
  design, not a high-availability production topology.
- Keycloak port 8080 accepts only the AWS-managed CloudFront origin prefix list.
- Browsers use a separate HTTPS CloudFront distribution. The AWS default
  certificate works without a custom domain.
- The assistant is a third Lambda Function URL outside the VPC. It receives no
  database DSN; it calls the authenticated governed API and writes audits back
  through that API.

## Hand the deployment to GitHub Actions

The deploy script exists to create the stack **once**. Every deployment after
that should come from CI.

```powershell
.\scripts\setup-github-actions.ps1     # or ./scripts/setup-github-actions.sh
```

It reads `terraform output` and publishes every secret and variable the
workflows need, so nothing is copied by hand. Two things it cannot do for you:

- create the `production-demo` environment (Settings → Environments). The deploy
  jobs declare it, and the IAM trust policy names it in the accepted subject.
- set `github_repository`. Without it Terraform never creates the OIDC provider
  or the CI role, the apply still succeeds, and CI has nothing to assume. The
  deploy scripts now detect it with `gh` and warn when they cannot.

Then:

```bash
gh workflow run deploy.yml                        # everything, in order
gh workflow run deploy.yml -f seed_warehouse=true # and reload the warehouse
```

### What the pipeline actually does

| Workflow | Trigger | Does |
|---|---|---|
| `deploy.yml` | manual | Runs the two below in order, then verifies all three tiers |
| `backend.yml` | push outside `docs/`, `web/` | Gates → build → push to ECR → roll three Lambdas → roll Keycloak → load the warehouse when needed → health check |
| `frontend.yml` | push under `web/` | Build → S3 → CloudFront invalidation → smoke test |
| `infrastructure.yml` | push under `infrastructure/aws/` | `fmt` and `validate` both roots |

The gates run **before** the image is built. Shipping an image whose golden
reconciliation failed would make the badge a decoration.

### Schema changes reach the deployed database

RDS is private, so a runner cannot connect to it. `backend.yml` instead runs a
fixed SSM document on the in-VPC Keycloak/NAT host, which loads the warehouse
from the image that was just built and tested.

It does not run on every push — a load rebuilds `tr_gov` and drops entitlements
granted since the last one. It runs when `sql/` or `etl/` changed, when
`seed_warehouse` is requested, or when the diff cannot be computed (a first
push), because the load is deterministic and skipping it wrongly is the more
expensive mistake.

Set the `TRANSFEROPS_OPERATOR` repository variable to your login address and the
load re-grants your entitlement in the same command. Without it, the console
after a reload is correctly enforcing an empty scope, which looks exactly like a
broken deployment.

### What CI is not allowed to do

The role can push images, update the three functions it owns, publish the
console bucket, invalidate the distribution, and run two named SSM documents. It
cannot create a VPC, an RDS instance or an IAM role, and `ssm:SendCommand` is
scoped to those two documents — `AWS-RunShellScript` is not among them, so CI
cannot run arbitrary commands on the host.

That is why `terraform apply` stays with the operator: granting CI enough IAM to
provision the stack would be a far larger privilege than deploying to it. State
is local for the same reason (`infrastructure/aws/providers.tf`).

No AWS access key exists anywhere. GitHub mints a short-lived OIDC token scoped
to this repository and the `production-demo` environment.

## Teardown

PowerShell:

```powershell
.\scripts\destroy-aws-student.ps1
```

Bash:

```bash
./scripts/destroy-aws-student.sh
```

Application state is destroyed first and the ECR bootstrap state second. This
dependency order prevents functions from referencing repositories while they
are being deleted.

## Troubleshooting

```powershell
aws ssm start-session --target (terraform -chdir=infrastructure/aws output -raw keycloak_instance_id)
terraform -chdir=infrastructure/aws output -raw cost_posture
```

If email fails, verify the relay permits the configured sender, uses the correct
TLS mode and port, and that the password is an App Password/token rather than a
normal mailbox password. If API health fails, first confirm the Keycloak/NAT EC2
instance is running because private Lambda internet egress depends on it.
