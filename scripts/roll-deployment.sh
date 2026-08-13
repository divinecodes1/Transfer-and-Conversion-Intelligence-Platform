#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: deploy from this machine.
#
#   ./scripts/roll-deployment.sh
#
# Rolls the running Container Apps to the images CI has already published, and
# uploads the console to the storage static website.
#
# WHY THIS EXISTS. Deploying from GitHub Actions needs a service principal, and
# a service principal needs an app registration in the directory. A managed
# tenant -- universities in particular -- commonly sets
# allowedToCreateApps=false, which blocks that for everyone but an administrator.
#
# ARM rights and DIRECTORY rights are different things: you can own the whole
# subscription and still be unable to create an identity in the directory behind
# it. So the split is: CI does everything that needs no Azure identity (tests,
# building and publishing images), and the rollout happens here, under your own
# `az login`, which already has the rights it needs.
#
# Nothing about the architecture changes. The same images, the same revisions.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/terraform"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n'; bold "==> $*"; }

# A datestamped, immutable tag. Never `latest`: Container Apps creates a new
# revision only when the image reference changes, so re-pushing `latest` and
# calling `update` is a no-op that looks like a successful deploy.
TAG="${1:-$(date +%Y%m%d).$(date +%H%M)}"

SKIP_BUILD=false
[[ "${2:-}" == "--no-build" || "${1:-}" == "--no-build" ]] && SKIP_BUILD=true
[[ "${1:-}" == "--no-build" ]] && TAG="$(date +%Y%m%d).$(date +%H%M)"

for tool in az terraform docker; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed."
done
az account show >/dev/null 2>&1 || die "Not logged in. Run: az login"

step "Reading the deployment"

cd "${TF_DIR}"
tf() { terraform output -raw "$1" 2>/dev/null || true; }

RESOURCE_GROUP="$(tf resource_group)"
[[ -n "${RESOURCE_GROUP}" ]] || die "No terraform state here. Deploy first."

API_IMAGE="$(terraform output -raw api_image 2>/dev/null || true)"
STORAGE_ACCOUNT="$(tf storage_account)"
API_URL="$(tf api_url)"
WEB_URL="$(tf web_url)"

# Read the app names from Azure rather than reconstructing them, so a rename
# does not silently roll nothing.
API_APP="$(az containerapp list -g "${RESOURCE_GROUP}" \
  --query "[?contains(name,'api')].name | [0]" -o tsv)"
KEYCLOAK_APP="$(az containerapp list -g "${RESOURCE_GROUP}" \
  --query "[?contains(name,'auth')].name | [0]" -o tsv)"

# Whatever the apps are running now tells us the registry, so this script does
# not need to know whether the deployment is on GHCR or ACR.
CURRENT_IMAGE="$(az containerapp show -n "${API_APP}" -g "${RESOURCE_GROUP}" \
  --query "properties.template.containers[0].image" -o tsv)"
REGISTRY_BASE="${CURRENT_IMAGE%:*}"

info "Resource group ${RESOURCE_GROUP}"
info "API app        ${API_APP}"
info "Keycloak app   ${KEYCLOAK_APP:-<none>}"
info "Current image  ${CURRENT_IMAGE}"
info "Rolling to tag ${TAG}"

cd "${REPO_ROOT}"

# Registry host, derived from what is deployed rather than configured here, so
# this works whether the deployment is on ACR or a public registry.
REGISTRY_HOST="${REGISTRY_BASE%%/*}"

# ---- Build and push ---------------------------------------------------------
if ! $SKIP_BUILD; then
  step "Building and pushing to ${REGISTRY_HOST}"

  docker info >/dev/null 2>&1 || die "Docker is not running."

  if [[ "${REGISTRY_HOST}" == *.azurecr.io ]]; then
    # `az acr login` exchanges your existing Azure CLI session for a registry
    # token. It needs no service principal and no stored password -- which is
    # precisely why local pushing works here while CI cannot.
    info "az acr login"
    az acr login --name "${REGISTRY_HOST%%.*}" --output none \
      || die "Could not log in to ${REGISTRY_HOST}. Do you have AcrPush on it?"
  fi

  info "API image"
  docker build -t "${REGISTRY_BASE}:${TAG}" "${REPO_ROOT}"
  docker push "${REGISTRY_BASE}:${TAG}"

  if [[ -n "${KEYCLOAK_APP}" ]]; then
    KC_CURRENT="$(az containerapp show -n "${KEYCLOAK_APP}" -g "${RESOURCE_GROUP}" \
      --query "properties.template.containers[0].image" -o tsv)"
    KC_BASE="${KC_CURRENT%:*}"
    info "Keycloak image (realm + themes baked in)"
    docker build -f "${REPO_ROOT}/infrastructure/docker/keycloak/Dockerfile" \
      -t "${KC_BASE}:${TAG}" "${REPO_ROOT}"
    docker push "${KC_BASE}:${TAG}"
  fi
else
  info "Skipping the build; rolling to an existing ${TAG}."
fi

# ---- Roll every app in the group --------------------------------------------
# Enumerated from Azure rather than listed here, so an app added later (the
# agent service, a future worker) is rolled without editing this script.
step "Rolling container apps"

for app in $(az containerapp list -g "${RESOURCE_GROUP}" --query "[].name" -o tsv); do
  current="$(az containerapp show -n "${app}" -g "${RESOURCE_GROUP}" \
    --query "properties.template.containers[0].image" -o tsv)"
  base="${current%:*}"
  az containerapp update -n "${app}" -g "${RESOURCE_GROUP}" \
    --image "${base}:${TAG}" --output none
  info "$(printf '%-20s %s' "${app}" "${base}:${TAG}")"
done

if [[ -n "${KEYCLOAK_APP}" ]]; then
  info "Keycloak sits at min_replicas 0, so this updates the revision the next"
  info "sign-in cold-starts into rather than restarting anything now."
fi

step "Publishing the console"

if [[ -d "${REPO_ROOT}/web/dist" ]]; then
  # --auth-mode login is required, not preferred: the storage account has
  # shared_access_key_enabled = false, so there is no key to fall back on.
  az storage blob upload-batch \
    --account-name "${STORAGE_ACCOUNT}" \
    --auth-mode login \
    --destination '$web' \
    --source "${REPO_ROOT}/web/dist" \
    --overwrite --output none
  # Hashed asset names are safe to cache hard; index.html is not. A cached index
  # keeps pointing at the previous bundle and the deploy appears to do nothing.
  az storage blob update \
    --account-name "${STORAGE_ACCOUNT}" \
    --auth-mode login --container-name '$web' --name index.html \
    --content-cache-control "no-cache, must-revalidate" --output none
  info "uploaded $(find "${REPO_ROOT}/web/dist" -type f | wc -l) files"
else
  warn "web/dist not found -- skipping the console."
  warn "Build it first:  cd web && npm run build"
fi

step "Smoke test"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "${API_URL}/health" || true)"
case "${code}" in
  200) info "API healthy (unauthenticated access open -- auth_mode is demo)." ;;
  401) info "API healthy and refusing unauthenticated callers, which is correct." ;;
  *)   warn "API returned ${code:-no response}; it may still be cold-starting." ;;
esac

printf '\n'
bold "==> Deployed"
info "Console  ${WEB_URL}"
info "API      ${API_URL}"
info "Tag      ${TAG}"
printf '\n'
info "Record the tag in infrastructure/terraform/terraform.tfvars so the next"
info "terraform plan does not propose rolling back to the previous image:"
info "  api_image      = \"${REGISTRY_BASE}:${TAG}\""
printf '\n'
