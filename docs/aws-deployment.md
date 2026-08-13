# AWS Student Deployment

From an empty AWS account to a public demo, with no manual console steps.

Architecture: [aws/architecture.md](../aws/architecture.md) ·
Costs: [aws/cost-strategy.md](../aws/cost-strategy.md) ·
Security: [aws/security.md](../aws/security.md)

---

## Prerequisites

1. An **AWS account** — check which free tier: `aws freetier get-free-tier-usage --region us-east-1`
2. **AWS CLI v2**, authenticated (`aws configure` or `aws sso login`)
3. **Terraform** ≥ 1.6
4. **Docker**, running
5. **Python 3.12** for the loader
6. **GitHub CLI** (`gh`) for wiring CI
7. *Optional:* a model API key — without one it deploys in `mock` mode and every
   AI surface still works

---

## One command

```bash
export TRANSFEROPS_OPERATOR=you@university.edu   # gets PLATFORM_ADMIN
./scripts/deploy-aws-student.sh
```

Checks prerequisites, detects your free tier and public IP, applies Terraform,
builds and pushes both images, points the Lambda functions at them, loads the
warehouse, publishes the console, grants you access, and prints the URLs.

Safe to re-run. Takes 10–15 minutes; RDS is the slow part.

---

## Step by step

### 1. Configure

```bash
cd infrastructure/aws
cp terraform.tfvars.example terraform.tfvars
```

**Set `budget_alert_emails`** — AWS never stops spending on its own, so the
alert is the only early warning:

```hcl
monthly_budget_amount = 30
budget_alert_emails   = ["you@university.edu"]
allowed_client_ip     = "203.0.113.42/32"   # curl -s https://checkip.amazonaws.com
github_repository     = "divinecodes1/Transfer-and-Conversion-Intelligence-Platform"
```

Secrets go in the environment, never the file:

```bash
export TF_VAR_ai_api_key="gsk_..."   # omit entirely for mock mode
```

### 2. Provision

```bash
terraform init
terraform plan      # read it
terraform apply
```

### 3. Build and push both images

```bash
REGION=$(terraform output -raw region)
API_REPO=$(terraform output -raw ecr_api_repository)
KC_REPO=$(terraform output -raw ecr_keycloak_repository)

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${API_REPO%%/*}"

# The base image, then the Lambda image on top of it. Two stages so the
# deployed artefact and the local one differ only in packaging.
docker build -t transfer-intelligence:base .
docker build -f infrastructure/docker/lambda/Dockerfile \
  --build-arg BASE_IMAGE=transfer-intelligence:base -t "$API_REPO:latest" .
docker push "$API_REPO:latest"

# Keycloak, realm and themes baked in — EC2 has no bind mount either.
docker build -f infrastructure/docker/keycloak/Dockerfile -t "$KC_REPO:latest" .
docker push "$KC_REPO:latest"

for fn in $(terraform output -raw api_function_name) $(terraform output -raw refresh_function_name); do
  aws lambda update-function-code --function-name "$fn" --image-uri "$API_REPO:latest"
  aws lambda wait function-updated --function-name "$fn"
done
```

### 4. Load the warehouse

```bash
./scripts/seed-demo-data.sh
```

Needs `allowed_client_ip` to admit you. Runs the same loader the local build
uses, so the cloud warehouse is identical to the one the golden gate asserts.

### 5. Publish the console

```bash
cd web && npm ci && npm run build && cd ..

BUCKET=$(terraform -chdir=infrastructure/aws output -raw console_bucket)
DIST=$(terraform -chdir=infrastructure/aws output -raw cloudfront_distribution_id)

# Hashed assets cache for a year; index.html must not, or the CDN keeps serving
# the previous bundle and the deploy appears to do nothing.
aws s3 sync web/dist "s3://$BUCKET" --delete --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp web/dist/index.html "s3://$BUCKET/index.html" \
  --cache-control "no-cache,must-revalidate"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html"
```

### 6. Grant yourself access

A verified Keycloak account still holds **no entitlement** — the platform
working as designed. The deploy script does this when `TRANSFEROPS_OPERATOR` is
set; by hand:

```sql
INSERT INTO tr_gov.app_user (username, display_name, email)
VALUES ('you@university.edu', 'Your Name', 'you@university.edu');

INSERT INTO tr_gov.user_role (username, role_code)
VALUES ('you@university.edu', 'PLATFORM_ADMIN');

INSERT INTO tr_gov.data_entitlement (username, dimension_type, dimension_value, valid_from, valid_to)
VALUES ('you@university.edu', 'PORTFOLIO', '*', DATE '2020-01-01', NULL);
```

`sql/09_entitlements.sql` drops these tables on reload, so put the grant there
to survive a rebuild.

---

## Continuous deployment

```bash
./scripts/setup-github-actions.sh
```

Reads the deployed stack and pushes every secret and variable. **The IAM role
already exists** — Terraform created it, because on AWS the OIDC provider and
role live inside your account and need no administrator.

> This is what the Azure attempt could not do. Federated login there needed an
> Entra app registration; the university tenant sets `allowedToCreateApps =
> false`; and owning the subscription did not help, because ARM rights and
> directory rights are separate. There is no directory in the way here.

Then create the environment the deploy jobs declare: **GitHub → Settings →
Environments → `production-demo`**, or the federated credential subject will not
match.

Push to `main` and the backend workflow tests, builds both images, pushes to
ECR and rolls both Lambda functions. Infrastructure only ever `plan`s
automatically; `apply` needs a manual dispatch with a typed confirmation.

---

## Verifying

```bash
curl -s "$(terraform -chdir=infrastructure/aws output -raw api_url)healthz"
```

`{"status":"healthy"}` means the function is up **and** reached the warehouse.
A 503 means it is running but cannot reach RDS — a different problem.

Then open the console URL and sign in.

---

## First boot of Keycloak

The instance pulls its image, creates its database and imports the realm on
first boot — a few minutes. Watch it:

```bash
aws ssm start-session --target $(terraform -chdir=infrastructure/aws output -raw keycloak_instance_id)
sudo journalctl -u keycloak -f
```

No SSH key needed — there is no port 22 rule at all.

---

## Tearing it down

```bash
./scripts/destroy-aws-student.sh
```

Also checks for what `terraform destroy` misses: **unattached Elastic IPs** and
**available EBS volumes** both bill while doing nothing and appear in no
"running resources" view.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Lambda returns 500 immediately | image not pushed yet | step 3 |
| `/healthz` returns 503 | warehouse not loaded, or SG blocks Lambda | step 4; check the database SG |
| Loader cannot connect | `allowed_client_ip` unset or your IP changed | update it and re-apply |
| Console shows a blank page | `index.html` cached by CloudFront | invalidate `/index.html` |
| Deep link 404s | CloudFront error responses missing | `site.tf` maps 403/404 → `/index.html` |
| Sign-in redirects to an error | realm origin mismatch | the realm resolves `${TRANSFEROPS_WEB_ORIGIN}` at import; re-create the instance to re-import |
| "Your account is verified" screen | no entitlement | step 6 |
| Registration never sends email | no SMTP relay | expected; use the operator grant |
| Keycloak unreachable for minutes | first boot | watch `journalctl -u keycloak` |
| AI panels show placeholders | `ai_provider = "mock"` | expected; see [openai-configuration.md](openai-configuration.md) |
