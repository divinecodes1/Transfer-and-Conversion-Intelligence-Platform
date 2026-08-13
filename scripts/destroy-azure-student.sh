#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: tear down the Azure demo.
#
# The most important cost control in the repository. A student credit is finite
# and a stack left running over a holiday is the usual way it disappears, so
# destroying has to be as easy as deploying -- and obviously safe to reach for.
#
#   ./scripts/destroy-azure-student.sh
#
# Deletes the resource group and everything in it, including the database and
# every uploaded document. Nothing here is precious: the warehouse rebuilds from
# sql/ and the generator in about a minute.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/terraform"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

command -v terraform >/dev/null 2>&1 || die "terraform is not installed."
command -v az >/dev/null 2>&1 || die "az is not installed."

az account show >/dev/null 2>&1 || die "Not logged in. Run: az login"

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"
export ARM_SUBSCRIPTION_ID="${SUBSCRIPTION_ID}"
export TF_VAR_subscription_id="${SUBSCRIPTION_ID}"

cd "${TF_DIR}"

if [[ ! -f terraform.tfstate && ! -d .terraform ]]; then
  die "No Terraform state here. Either nothing is deployed, or you are in the wrong checkout."
fi

terraform init -input=false >/dev/null

RESOURCE_GROUP="$(terraform output -raw resource_group 2>/dev/null || echo "unknown")"

printf '\n'
bold "This will permanently delete:"
printf '\n'
info "Subscription   ${SUBSCRIPTION_NAME}"
info "Resource group ${RESOURCE_GROUP}"
printf '\n'
warn "Everything goes, including:"
warn "  - the PostgreSQL server and BOTH databases (warehouse and Keycloak)"
warn "  - every registered Keycloak user and the realm's runtime state"
warn "  - all blobs: documents, generated reports, exports"
warn "  - the Static Web App and its URL (a new deploy gets a new hostname)"
printf '\n'
info "Reproducible from this repository: the warehouse, the realm import and"
info "the entire infrastructure. Anything typed into the running system is not."
printf '\n'

# Show what is about to go, from Azure rather than from state, so a resource
# Terraform lost track of is still visible before it is deleted.
if az group show --name "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  bold "Resources currently in ${RESOURCE_GROUP}:"
  az resource list --resource-group "${RESOURCE_GROUP}" \
    --query "[].{name:name, type:type}" -o table | sed 's/^/    /'
  printf '\n'
fi

read -r -p "Type the resource group name to confirm: " confirmation
[[ "${confirmation}" == "${RESOURCE_GROUP}" ]] || die "Name did not match. Nothing was deleted."

printf '\n'
bold "==> Destroying"
terraform destroy -input=false -auto-approve

# Terraform destroys what it created. A resource added by hand -- or one left
# behind by a partial apply -- would survive and keep billing, which is the
# outcome this script exists to prevent.
if az group show --name "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  printf '\n'
  warn "The resource group still exists, so something in it is not in Terraform state:"
  az resource list --resource-group "${RESOURCE_GROUP}" \
    --query "[].{name:name, type:type}" -o table | sed 's/^/    /'
  printf '\n'
  read -r -p "  Delete the resource group outright? [y/N] " reply
  if [[ "${reply}" =~ ^[Yy]$ ]]; then
    az group delete --name "${RESOURCE_GROUP}" --yes --no-wait
    info "Deletion started in the background."
  else
    warn "Left in place. It will continue to bill."
  fi
fi

printf '\n'
bold "==> Done"
info "Confirm nothing is left: az resource list --output table"
info "Redeploy any time with: ./scripts/deploy-azure-student.sh"
printf '\n'
