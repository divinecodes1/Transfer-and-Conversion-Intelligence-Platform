# Azure Student Deployment

From an empty subscription to a public demo, with no manual portal steps.

Architecture and rationale: [azure/architecture.md](../azure/architecture.md).
Costs: [azure/cost-strategy.md](../azure/cost-strategy.md).

---

## Prerequisites

1. **Azure for Students** — $100 credit, 12 months, no credit card required
2. **Azure CLI** — `az version` ≥ 2.60
3. **Terraform** ≥ 1.6
4. **Docker**, running
5. **A GitHub account** (images go to GitHub Container Registry)
6. **Python 3.12** for the loader
7. *Optional:* a model API key. Without one the platform deploys in `mock` mode
   and every AI surface still works.

---

## One command

```bash
export GITHUB_TOKEN=ghp_...        # needs write:packages
./scripts/deploy-azure-student.sh
```

It checks prerequisites, logs in, registers resource providers, detects your
public IP, builds and pushes the image, applies Terraform, loads the warehouse,
wakes Keycloak, smoke-tests the API and prints the URLs.

Safe to re-run.

---

## Step by step

If you prefer to drive it yourself:

### 1. Sign in and pick the subscription

```bash
az login
az account set --subscription "Azure for Students"
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

### 2. Register resource providers

On a fresh subscription these are not registered, and the failure arrives several
minutes into `apply` with an unhelpful message:

```bash
for ns in Microsoft.App Microsoft.DBforPostgreSQL Microsoft.OperationalInsights \
          Microsoft.Insights Microsoft.KeyVault Microsoft.Storage Microsoft.Web; do
  az provider register --namespace "$ns"
done
```

### 3. Configure

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit it. **Set `budget_alert_emails`** — it is the only early warning you get:

```hcl
budget_alert_emails   = ["you@university.edu"]
monthly_budget_amount = 10
allowed_client_ip     = "203.0.113.42"   # curl -s https://api.ipify.org
api_image             = "ghcr.io/yourname/transfer-intelligence:latest"
```

Secrets go in the environment, never in the file:

```bash
export TF_VAR_subscription_id="$ARM_SUBSCRIPTION_ID"
export TF_VAR_ai_api_key="sk-..."        # omit entirely for mock mode
```

### 4. Build and push both images

Two images: the API, and Keycloak with the realm and themes baked in.

```bash
docker build -t ghcr.io/yourname/transfer-intelligence:latest .
docker build -f infrastructure/docker/keycloak/Dockerfile \
             -t ghcr.io/yourname/transfer-intelligence-keycloak:latest .

echo "$GITHUB_TOKEN" | docker login ghcr.io -u yourname --password-stdin
docker push ghcr.io/yourname/transfer-intelligence:latest
docker push ghcr.io/yourname/transfer-intelligence-keycloak:latest
```

Make the package **public** in GitHub → Packages → Package settings, so Container
Apps can pull it without a credential. To keep it private, set
`image_registry_server`/`_username`/`_password`, or `use_acr = true` (which adds
a fixed ~5 USD/month).

### 5. Provision

```bash
terraform init
terraform plan       # read it
terraform apply
```

About 10–15 minutes; PostgreSQL is the slow part.

### 6. Load the warehouse

```bash
./scripts/seed-demo-data.sh
```

Requires `allowed_client_ip` to admit you. It generates the synthetic portfolio
and runs the same loader the local build uses, so the cloud warehouse is
identical to the one the golden gate asserts against.

### 7. The realm — nothing to do

`keycloak/realm-export.json` declares its origins as
`${TRANSFEROPS_WEB_ORIGIN}`, resolved at import time. Terraform passes the
Static Web App's hostname, so the deployed console is an allowed redirect origin
without anyone opening the admin console.

Two things make this work, and both were failures worth naming:

- **The realm is baked into the Keycloak image**
  (`infrastructure/docker/keycloak/Dockerfile`). Container Apps cannot
  bind-mount a single file the way compose does, so a stock `quay.io` image
  would start with **no realm at all** and sign-in would be impossible.
- **The image is pre-built** (`kc.sh build`), which is what makes
  `start --optimized` valid and keeps the cold start short.

To add another origin permanently, edit the realm file and redeploy — it is
version-controlled like everything else.

> **Self-registration does not complete in Azure** unless you configure an SMTP
> relay. `verifyEmail` is on, and with no relay Keycloak cannot send the
> verification message. Locally, Mailpit catches it and the flow works end to
> end. Set `keycloak_smtp_host` (and user/password) to restore it; otherwise use
> the operator grant in step 9.

### 8. Configure and deploy the console

The console needs to know where the API and Keycloak are. In GitHub → Settings →
Secrets and variables → Actions → **Variables**:

| Variable | Value |
|---|---|
| `VITE_TRANSFEROPS_API` | `terraform output -raw api_url` |
| `VITE_KEYCLOAK_URL` | `terraform output -raw keycloak_url` |
| `VITE_KEYCLOAK_REALM` | `transferops` |
| `VITE_KEYCLOAK_CLIENT_ID` | `transferops-api` |
| `VITE_TRANSFEROPS_AUTH` | `oidc` |

All of this is done for you by:

```bash
./scripts/setup-github-actions.sh
```

Then push, or run the Frontend workflow manually.

### 9. Grant yourself access

A verified Keycloak account still holds no entitlement — that is the platform
working as designed, and it is the wall every first deployment hits.

`deploy-azure-student.sh` does this for you, granting `PLATFORM_ADMIN` over all
portfolios to the signed-in Azure user (the realm uses email as the username).
Override with:

```bash
TRANSFEROPS_OPERATOR=you@university.edu ./scripts/deploy-azure-student.sh
```

To do it by hand, or to grant somebody else:

```sql
INSERT INTO tr_gov.app_user (username, display_name, email)
VALUES ('you@university.edu', 'Your Name', 'you@university.edu');

INSERT INTO tr_gov.user_role (username, role_code)
VALUES ('you@university.edu', 'PLATFORM_ADMIN');

INSERT INTO tr_gov.data_entitlement (username, dimension_type, dimension_value, valid_from, valid_to)
VALUES ('you@university.edu', 'PORTFOLIO', '*', DATE '2020-01-01', NULL);
```

`sql/09_entitlements.sql` drops and recreates these tables, so put the grant in
that file to survive a reload.

---

## Continuous deployment

```bash
./scripts/setup-github-actions.sh
```

One command. It creates the Entra app registration CI signs in as, adds the
federated credentials, grants the roles, and pushes every secret and variable
from `terraform output` — nothing is copied by hand.

**No client secret is ever created.** GitHub mints a short-lived OIDC token for
a specific repo, branch and environment; Entra trusts that instead of a
password. There is no deployment credential to leak or rotate.

### What it sets

**Secrets** — private, never rendered into the browser bundle:

| Secret | Purpose |
|---|---|
| `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` | federated OIDC login |
| `AZURE_RESOURCE_GROUP` / `AZURE_CONTAINER_APP` | which app to roll |
| `AZURE_STORAGE_ACCOUNT` | where the console is published |
| `TRANSFEROPS_AI_API_KEY` | model key, optional — skip it to stay in mock mode |

**Variables** — compiled into the console bundle and therefore **public**. Only
values safe to publish appear here; `tests/web_checks.py` asserts the built
console carries no key and no connection string:

| Variable | Source |
|---|---|
| `VITE_TRANSFEROPS_API` | `terraform output -raw api_url` |
| `VITE_KEYCLOAK_URL` | `terraform output -raw keycloak_url` |
| `VITE_KEYCLOAK_REALM` / `VITE_KEYCLOAK_CLIENT_ID` | `transferops` / `transferops-api` |
| `VITE_TRANSFEROPS_AUTH` | `oidc` |
| `BUDGET_ALERT_EMAIL` | read from `terraform.tfvars` |

### Roles it grants

Scoped to **this resource group only** — CI can redeploy this stack and touch
nothing else in the subscription.

| Role | Scope | Why |
|---|---|---|
| `Contributor` | resource group | roll the Container App to a new image |
| `Storage Blob Data Contributor` | the storage account | the account has `shared_access_key_enabled = false`, so there is no key — uploads authenticate as this identity |

`terraform apply` from CI needs more, because Contributor cannot create the role
assignments Terraform makes. Either apply from your laptop, or:

```bash
./scripts/setup-github-actions.sh --with-terraform
```

which additionally grants `Role Based Access Control Administrator`.

### Then

Create the environment the deploy jobs declare — **GitHub → Settings →
Environments → `production-demo`** — or the federated credential will not match.

Push to `main` and the backend workflow tests, builds, pushes and rolls the
Container App. Infrastructure changes only ever `plan` automatically; `apply`
requires a manual dispatch with a typed confirmation.

---

## Verifying

```bash
curl -s "$(terraform output -raw api_url)/health"
```

**A 401 is the correct answer** in `enforce` mode: the service is up and refusing
an unauthenticated caller.

Then open `terraform output -raw web_url`, sign in, and check the Overview
screen shows portfolio numbers.

---

## Before a live demonstration

Keycloak is scaled to zero and takes **40–60 seconds** to serve the first
sign-in. Either warm it:

```bash
curl -s "$(terraform output -raw keycloak_url)/realms/transferops/.well-known/openid-configuration" >/dev/null
```

or hold it warm for the session and set it back afterwards:

```bash
az containerapp update --name ti-auth-student \
  --resource-group rg-transfer-intelligence-student --min-replicas 1
```

Held warm it is roughly a third of the student credit per month.

---

## Tearing it down

```bash
./scripts/destroy-azure-student.sh
```

Prompts you to type the resource group name, then removes everything and checks
for resources Terraform did not know about. Everything rebuilds from this
repository.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SubscriptionNotRegistered` | provider not registered | step 2 |
| Container App won't start | image not pullable | make the GHCR package public, or set registry credentials |
| API returns 500 on `/health` | warehouse not loaded | `./scripts/seed-demo-data.sh` |
| Loader can't connect | firewall | set `allowed_client_ip` and re-apply |
| Sign-in redirects to an error | realm imported before the console existed | re-run the deploy script, or add the origin to the realm file and redeploy |
| Keycloak starts then exits | `--optimized` without a built image | use the image from `infrastructure/docker/keycloak/`, not stock `quay.io` |
| Login page 404s on the realm | realm never imported (no realm file in the image) | same — build the image in this repo |
| "Your account is verified" screen | no entitlement | step 9 |
| Registration never sends email | no SMTP relay in Azure | expected; set `keycloak_smtp_host` or use the operator grant |
| First sign-in hangs ~60s | Keycloak cold start | expected; warm it first |
| AI panels show placeholders | `ai_provider = "mock"` | expected; see [openai-configuration.md](openai-configuration.md) |
