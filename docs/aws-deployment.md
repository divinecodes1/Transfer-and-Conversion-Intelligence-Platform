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

## CI rollout

After the first deployment:

```bash
./scripts/setup-github-actions.sh
```

GitHub Actions uses OIDC, pushes both images, rolls all three Lambda functions,
and invokes the constrained Keycloak rollout SSM document. No AWS access key is
stored in GitHub.

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
