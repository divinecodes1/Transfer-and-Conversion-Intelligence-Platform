#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: wire GitHub Actions to Azure.
#
#   ./scripts/setup-github-actions.sh
#
# Creates the Entra app registration CI signs in as, grants it exactly the roles
# it needs on this resource group, and pushes every secret and variable the three
# workflows read -- all from `terraform output`, so nothing is copied by hand.
#
# NO CLIENT SECRET IS EVER CREATED. Authentication uses federated credentials:
# GitHub mints a short-lived OIDC token for a specific repo, branch and
# environment, and Entra trusts that instead of a password. There is no
# deployment credential to leak, rotate or find in a screenshot two years later.
#
# Re-runnable. Existing app registrations, credentials and role assignments are
# reused rather than duplicated.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/terraform"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n'; bold "==> $*"; }

WITH_TERRAFORM=false
[[ "${1:-}" == "--with-terraform" ]] && WITH_TERRAFORM=true

# ---- 1. Prerequisites -------------------------------------------------------
step "Checking prerequisites"

for tool in az gh terraform; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed or not on PATH."
done
az account show >/dev/null 2>&1 || die "Not logged in to Azure. Run: az login"
gh auth status >/dev/null 2>&1 || die "Not logged in to GitHub. Run: gh auth login"

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
GH_REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

info "Subscription ${SUBSCRIPTION_ID}"
info "Tenant       ${TENANT_ID}"
info "Repository   ${GH_REPO}"

# ---- 2. Read the deployment -------------------------------------------------
step "Reading terraform outputs"

cd "${TF_DIR}"
[[ -d .terraform ]] || die "Terraform is not initialised here. Deploy first."

tf() { terraform output -raw "$1" 2>/dev/null || true; }

RESOURCE_GROUP="$(tf resource_group)"
[[ -n "${RESOURCE_GROUP}" ]] || die "No resource_group output. Has terraform apply run?"

API_URL="$(tf api_url)"
WEB_URL="$(tf web_url)"
KEYCLOAK_URL="$(tf keycloak_url)"
STORAGE_ACCOUNT="$(tf storage_account)"

# The API Container App's name follows the prefix/environment convention. Read
# it from Azure rather than reconstructing it, so a renamed app is still found.
CONTAINER_APP="$(az containerapp list --resource-group "${RESOURCE_GROUP}" \
  --query "[?contains(name, 'api')].name | [0]" -o tsv 2>/dev/null || true)"
KEYCLOAK_APP="$(az containerapp list --resource-group "${RESOURCE_GROUP}" \
  --query "[?contains(name, 'auth')].name | [0]" -o tsv 2>/dev/null || true)"

info "Resource group  ${RESOURCE_GROUP}"
info "Container App   ${CONTAINER_APP:-<not found>}"
info "Keycloak App    ${KEYCLOAK_APP:-<not found>}"
info "Storage account ${STORAGE_ACCOUNT}"
info "API             ${API_URL}"
info "Console         ${WEB_URL}"

cd "${REPO_ROOT}"

# ---- 3. App registration ----------------------------------------------------
step "Entra app registration for CI"

APP_NAME="transfer-intelligence-ci"
CLIENT_ID="$(az ad app list --display-name "${APP_NAME}" --query "[0].appId" -o tsv 2>/dev/null || true)"

# Managed tenants -- universities especially -- commonly set
# allowedToCreateApps=false, which blocks every non-admin from registering an
# application. Checked up front because the alternative is a raw Graph
# "Insufficient privileges" error two steps later, after roles have been
# touched, with nothing explaining that ARM rights and DIRECTORY rights are
# different things. You can own an entire subscription and still not be allowed
# to create an identity in the directory behind it.
CAN_CREATE_APPS="$(az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/policies/authorizationPolicy" \
  --query "defaultUserRolePermissions.allowedToCreateApps" -o tsv 2>/dev/null || echo "unknown")"

if [[ -z "${CLIENT_ID}" && "${CAN_CREATE_APPS}" == "false" ]]; then
  printf '\n'
  warn "This tenant does not permit you to register applications."
  warn "  tenant policy allowedToCreateApps = false"
  warn "  directory roles held             = none"
  printf '\n'
  info "Federated OIDC login from GitHub Actions needs a service principal, and"
  info "a service principal needs an app registration. Without one, the deploy"
  info "jobs cannot authenticate to Azure -- no workaround exists on the runner."
  printf '\n'
  info "What still works, and it is most of the value:"
  info "  - CI runs every test gate on each push"
  info "  - CI builds and publishes both images to GHCR (uses GITHUB_TOKEN,"
  info "    which needs no Azure identity at all)"
  info "  - you roll the deployment from this machine, where your own az login"
  info "    already has the ARM rights:  ./scripts/roll-deployment.sh"
  printf '\n'
  info "To enable CI deployment instead, ask your tenant administrator to either"
  info "set 'Users can register applications' to Yes, or create the app"
  info "registration and a federated credential for:"
  info "  repo:${GH_REPO}:environment:production-demo"
  printf '\n'

  AZURE_IDENTITY_AVAILABLE=false
else
  AZURE_IDENTITY_AVAILABLE=true
  if [[ -z "${CLIENT_ID}" ]]; then
    info "Creating ${APP_NAME}"
    CLIENT_ID="$(az ad app create --display-name "${APP_NAME}" --query appId -o tsv)"
  else
    info "Reusing ${APP_NAME} (${CLIENT_ID})"
  fi
fi

if $AZURE_IDENTITY_AVAILABLE; then
  # The service principal is the object role assignments actually attach to; the
  # app registration on its own cannot be granted anything.
  if ! az ad sp show --id "${CLIENT_ID}" >/dev/null 2>&1; then
    info "Creating service principal"
    az ad sp create --id "${CLIENT_ID}" >/dev/null
  fi
  SP_OBJECT_ID="$(az ad sp show --id "${CLIENT_ID}" --query id -o tsv)"
fi

# ---- 4. Federated credentials ----------------------------------------------
if $AZURE_IDENTITY_AVAILABLE; then
step "Federated credentials (no client secret)"

# One subject per context that needs to authenticate. The subject is matched
# exactly, so a token minted for a different repo, branch or environment is
# rejected -- which is what makes this safer than a shared secret.
add_federated() {
  local name="$1" subject="$2"
  if az ad app federated-credential list --id "${CLIENT_ID}" \
       --query "[?name=='${name}'] | [0].name" -o tsv 2>/dev/null | grep -q .; then
    info "exists  ${name}"
    return
  fi
  info "create  ${name}  ->  ${subject}"
  az ad app federated-credential create --id "${CLIENT_ID}" --parameters "{
    \"name\": \"${name}\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"${subject}\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" >/dev/null
}

# The deploy jobs in every workflow declare `environment: production-demo`, and
# GitHub puts that in the token subject -- so without this one, deploys fail
# even though the branch credential exists.
add_federated "github-env-production-demo" "repo:${GH_REPO}:environment:production-demo"
add_federated "github-branch-main"         "repo:${GH_REPO}:ref:refs/heads/main"
add_federated "github-pull-request"        "repo:${GH_REPO}:pull_request"

# ---- 5. Role assignments ----------------------------------------------------
step "Role assignments, scoped to this resource group only"

RG_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}"

assign() {
  local role="$1" scope="$2"
  if az role assignment list --assignee "${SP_OBJECT_ID}" --scope "${scope}" \
       --query "[?roleDefinitionName=='${role}'] | [0].id" -o tsv 2>/dev/null | grep -q .; then
    info "exists  ${role}"
    return
  fi
  info "grant   ${role}"
  az role assignment create --assignee-object-id "${SP_OBJECT_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "${role}" --scope "${scope}" >/dev/null
}

# Enough to roll the Container App to a new image. Scoped to the resource group,
# not the subscription: CI can redeploy this stack and touch nothing else.
assign "Contributor" "${RG_SCOPE}"

# The storage account has shared key access DISABLED, so the console cannot be
# uploaded with an account key -- there isn't one. Uploads authenticate as this
# identity instead, which is why the data-plane role is required and not just
# Contributor.
if [[ -n "${STORAGE_ACCOUNT}" ]]; then
  assign "Storage Blob Data Contributor" \
    "${RG_SCOPE}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT}"
fi

if $WITH_TERRAFORM; then
  # terraform apply from CI creates role assignments of its own (the managed
  # identity's access to blob and Key Vault), and Contributor cannot grant roles.
  warn "Granting 'Role Based Access Administrator' so CI can run terraform apply."
  warn "Skip --with-terraform and apply from your laptop if you would rather not."
  assign "Role Based Access Control Administrator" "${RG_SCOPE}"
fi

fi  # AZURE_IDENTITY_AVAILABLE

# ---- 6. GitHub secrets ------------------------------------------------------
step "GitHub secrets"

set_secret() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    warn "skip    ${name} (no value)"
    return
  fi
  printf '%s' "${value}" | gh secret set "${name}" --repo "${GH_REPO}" >/dev/null
  info "set     ${name}"
}

if $AZURE_IDENTITY_AVAILABLE; then
  set_secret AZURE_CLIENT_ID       "${CLIENT_ID}"
  set_secret AZURE_TENANT_ID       "${TENANT_ID}"
  set_secret AZURE_SUBSCRIPTION_ID "${SUBSCRIPTION_ID}"
else
  info "Skipping the Azure login secrets -- there is no identity to log in as."
fi

# Set regardless: harmless without an identity, and already correct if a tenant
# administrator enables app registration later.
set_secret AZURE_RESOURCE_GROUP  "${RESOURCE_GROUP}"
set_secret AZURE_CONTAINER_APP   "${CONTAINER_APP}"
set_secret AZURE_KEYCLOAK_APP    "${KEYCLOAK_APP}"
set_secret AZURE_STORAGE_ACCOUNT "${STORAGE_ACCOUNT}"

# ---- 7. The model API key ---------------------------------------------------
step "Model API key (optional)"

# Read silently and never echoed. It reaches GitHub encrypted and reaches Azure
# as a Container Apps secret; it is never written to a file on this machine.
if [[ -n "${TRANSFEROPS_AI_API_KEY:-}" ]]; then
  set_secret TRANSFEROPS_AI_API_KEY "${TRANSFEROPS_AI_API_KEY}"
  info "Taken from the environment."
else
  info "Leave blank to keep the deployment on TRANSFEROPS_AI_PROVIDER=mock,"
  info "which needs no key and keeps every AI surface working."
  # `|| true` is load-bearing under `set -e`: with no TTY (CI, a piped shell)
  # read hits EOF and returns non-zero, which would abort the whole script at
  # the last step -- after the app registration and roles were already created.
  read -r -s -p "  API key (input hidden, Enter to skip): " ai_key || true
  printf '\n'
  if [[ -n "${ai_key}" ]]; then
    set_secret TRANSFEROPS_AI_API_KEY "${ai_key}"
    warn "Also set ai_provider in terraform.tfvars (openai|anthropic) and re-apply,"
    warn "or the key will sit unused while the app stays in mock mode."
  else
    info "Skipped -- staying in mock mode."
  fi
  unset ai_key
fi

# ---- 8. GitHub variables ----------------------------------------------------
step "GitHub variables (public, compiled into the console bundle)"

set_var() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    warn "skip    ${name} (no value)"
    return
  fi
  gh variable set "${name}" --repo "${GH_REPO}" --body "${value}" >/dev/null
  info "set     ${name} = ${value}"
}

# These are compiled into the browser bundle and are therefore PUBLIC. Only
# values safe to publish appear here -- no key, no connection string.
# tests/web_checks.py asserts the built console holds neither.
set_var VITE_TRANSFEROPS_API    "${API_URL}"
set_var VITE_KEYCLOAK_URL       "${KEYCLOAK_URL}"
set_var VITE_KEYCLOAK_REALM     "transferops"
set_var VITE_KEYCLOAK_CLIENT_ID "transferops-api"
set_var VITE_TRANSFEROPS_AUTH   "oidc"

BUDGET_EMAIL="$(grep -oE '"[^"]+@[^"]+"' "${TF_DIR}/terraform.tfvars" 2>/dev/null | head -1 | tr -d '"' || true)"
set_var BUDGET_ALERT_EMAIL "${BUDGET_EMAIL}"

# The switch the deploy jobs read. A repository VARIABLE rather than a secret,
# because job-level `if:` conditions cannot see the secrets context -- so a
# secret could not gate a job even though that is what it looks like it should
# do. False here means CI still tests and publishes images; only the Azure
# rollout is skipped.
set_var AZURE_DEPLOY_ENABLED "$($AZURE_IDENTITY_AVAILABLE && echo true || echo false)"

# ---- 9. Summary -------------------------------------------------------------
step "Done"

if $AZURE_IDENTITY_AVAILABLE; then
  cat <<SUMMARY

  CI signs in as    ${APP_NAME}
  Client id         ${CLIENT_ID}
  Scoped to         ${RESOURCE_GROUP}
  Authentication    federated OIDC -- no client secret exists

  Verify:
    gh secret list --repo ${GH_REPO}
    gh variable list --repo ${GH_REPO}

  Push, or run a workflow by hand:
    gh workflow run backend.yml
    gh workflow run frontend.yml

SUMMARY

  if ! $WITH_TERRAFORM; then
    warn "CI cannot run 'terraform apply' -- Contributor cannot create role"
    warn "assignments. Apply from your laptop, or re-run with --with-terraform."
  fi
else
  cat <<SUMMARY

  CI deployment      DISABLED (AZURE_DEPLOY_ENABLED=false)
                     the tenant does not permit the app registration it
                     would need to sign in with

  CI still does      run every test gate on each push
                     build and publish both images to GHCR

  You deploy with    ./scripts/roll-deployment.sh
                     using your own az login, which already has the rights

  Verify:
    gh secret list --repo ${GH_REPO}
    gh variable list --repo ${GH_REPO}

  If an administrator later enables app registration, re-run this script and
  it will create the identity and flip AZURE_DEPLOY_ENABLED to true.

SUMMARY
fi
