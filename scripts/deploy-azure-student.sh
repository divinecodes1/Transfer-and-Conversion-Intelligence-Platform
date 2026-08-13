#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: Azure student deployment.
#
# One command, from an empty subscription to a working public demo. Everything
# it does is Terraform or `az`; there is no step that says "now open the portal
# and click", because a step like that is a step nobody can repeat.
#
#   ./scripts/deploy-azure-student.sh
#
# Safe to re-run. Terraform converges, the loader rebuilds the warehouse from
# the SQL files, and the realm import is idempotent.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/terraform"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

step() { printf '\n'; bold "==> $*"; }

# ---- 1. Prerequisites -------------------------------------------------------
step "Checking prerequisites"

for tool in az terraform docker python3; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed or not on PATH."
  info "$tool $(command -v "$tool")"
done

# ---- 2. Azure login and subscription ---------------------------------------
step "Azure account"

if ! az account show >/dev/null 2>&1; then
  info "Not logged in; opening a browser."
  az login --only-show-errors >/dev/null
fi

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"
info "Subscription: ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})"

# A student subscription is a credit subscription: when the credit is gone the
# subscription is disabled rather than charged. Worth naming out loud, because
# it changes what "the budget alert fired" means.
if [[ "${SUBSCRIPTION_NAME}" != *"Student"* && "${SUBSCRIPTION_NAME}" != *"Free"* ]]; then
  warn "This does not look like an Azure for Students subscription."
  warn "Resources created here may be billed to a real payment method."
  read -r -p "  Continue anyway? [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]] || die "Stopped."
fi

export ARM_SUBSCRIPTION_ID="${SUBSCRIPTION_ID}"
export TF_VAR_subscription_id="${SUBSCRIPTION_ID}"

# Container Apps and PostgreSQL Flexible Server both need their resource
# providers registered. On a fresh subscription they are not, and the failure
# arrives several minutes into apply with an unhelpful message.
step "Registering resource providers (no-op if already registered)"
for ns in Microsoft.App Microsoft.ContainerService Microsoft.DBforPostgreSQL \
          Microsoft.OperationalInsights Microsoft.Insights Microsoft.KeyVault \
          Microsoft.Storage Microsoft.Web; do
  state="$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo NotRegistered)"
  if [[ "$state" != "Registered" ]]; then
    info "registering $ns"
    az provider register --namespace "$ns" --only-show-errors >/dev/null || true
  fi
done

# ---- 3. Inputs --------------------------------------------------------------
step "Deployment inputs"

# The operator's public IP, so the loader can reach the database. Without it the
# firewall admits only Azure services and the seed step cannot run.
CLIENT_IP="${TRANSFEROPS_CLIENT_IP:-$(curl -fsS https://api.ipify.org 2>/dev/null || true)}"
if [[ -z "${CLIENT_IP}" ]]; then
  warn "Could not detect your public IP; the loader will not be able to connect."
  warn "Set TRANSFEROPS_CLIENT_IP and re-run to seed the warehouse."
else
  info "Operator IP: ${CLIENT_IP}"
fi
export TF_VAR_allowed_client_ip="${CLIENT_IP}"

# Images go to GHCR under the current repo, avoiding a fixed ACR charge.
GH_REPO="${GITHUB_REPOSITORY:-$(git -C "${REPO_ROOT}" remote get-url origin 2>/dev/null \
  | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#' || true)}"
if [[ -z "${GH_REPO}" ]]; then
  die "Could not determine the GitHub repository. Set GITHUB_REPOSITORY=owner/name."
fi
IMAGE="ghcr.io/$(echo "${GH_REPO}" | tr '[:upper:]' '[:lower:]')"
export TF_VAR_api_image="${IMAGE}:latest"
info "Image: ${TF_VAR_api_image}"

if [[ -z "${TF_VAR_ai_api_key:-}" ]]; then
  info "No TF_VAR_ai_api_key set -- deploying with AI_PROVIDER=mock."
  info "Every AI surface still works; narratives are deterministic, not generated."
  export TF_VAR_ai_provider="${TF_VAR_ai_provider:-mock}"
fi

# ---- 4. Build and push the image -------------------------------------------
step "Building the container image"

if ! docker info >/dev/null 2>&1; then
  die "Docker is not running."
fi

docker build -t "${IMAGE}:latest" "${REPO_ROOT}"

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  info "Pushing to GHCR"
  echo "${GITHUB_TOKEN}" | docker login ghcr.io -u "${GITHUB_ACTOR:-$USER}" --password-stdin
  docker push "${IMAGE}:latest"
else
  warn "GITHUB_TOKEN not set; skipping the push."
  warn "Container Apps pulls from the registry, so the image must exist there."
  warn "Either export GITHUB_TOKEN (with write:packages) or let the backend"
  warn "workflow build and push, then re-run this script."
fi

# ---- 5. Provision -----------------------------------------------------------
step "Provisioning Azure resources"

cd "${TF_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve

API_URL="$(terraform output -raw api_url)"
WEB_URL="$(terraform output -raw web_url)"
KEYCLOAK_URL="$(terraform output -raw keycloak_url)"
RESOURCE_GROUP="$(terraform output -raw resource_group)"

# ---- 6. Load the warehouse --------------------------------------------------
step "Building the warehouse"

if [[ -n "${CLIENT_IP}" ]]; then
  cd "${REPO_ROOT}"
  # Role passwords are generated by Terraform and consumed by the loader, which
  # is the one component entitled to create them. They never touch a file.
  TRANSFEROPS_READER_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw reader_password)" \
  TRANSFEROPS_AUDITOR_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw auditor_password)" \
  TRANSFEROPS_AI_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw ai_password)" \
  DSN="$(terraform -chdir="${TF_DIR}" output -raw loader_dsn)" \
  bash -c '
    python3 etl/generate_data.py
    python3 etl/run.py --engine postgres --dsn "$DSN"
  '
  info "Warehouse loaded and data-quality gates passed."
else
  warn "Skipped: no operator IP, so the database is unreachable from here."
  warn "Run scripts/seed-demo-data.sh once the firewall admits you."
fi

# ---- 7. Wake Keycloak and import the realm ---------------------------------
step "Waking Keycloak"

# It is scaled to zero, so the first request pays a cold start. Doing it here
# means the first *human* to visit does not.
info "First start takes 40-60 seconds; waiting."
for attempt in $(seq 1 24); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
    "${KEYCLOAK_URL}/realms/master/.well-known/openid-configuration" || true)"
  if [[ "${code}" == "200" ]]; then
    info "Keycloak is up after ${attempt} attempt(s)."
    break
  fi
  sleep 10
done

warn "The realm's redirect URIs must include ${WEB_URL}."
warn "keycloak/realm-export.json ships with localhost origins only."
warn "See docs/azure-deployment.md -> 'Pointing the realm at the deployed console'."

# ---- 8. Smoke test ----------------------------------------------------------
step "Smoke test"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "${API_URL}/health" || true)"
case "${code}" in
  200) info "API healthy (unauthenticated access is open -- auth_mode is demo)." ;;
  401) info "API healthy and refusing unauthenticated callers, which is correct." ;;
  *)   warn "API returned ${code:-no response}. It may still be cold-starting." ;;
esac

# ---- 9. Summary -------------------------------------------------------------
step "Deployed"

cat <<SUMMARY

  Console       ${WEB_URL}
  API           ${API_URL}          (Swagger at /docs)
  Keycloak      ${KEYCLOAK_URL}
  Resource grp  ${RESOURCE_GROUP}

  Credentials, on demand:
    terraform -chdir=infrastructure/terraform output -raw keycloak_admin_password
    terraform -chdir=infrastructure/terraform output -raw postgres_admin_password

  Standing cost:
$(terraform -chdir="${TF_DIR}" output -raw cost_posture | sed 's/^/    /')

  Tear it all down with:
    ./scripts/destroy-azure-student.sh

SUMMARY
