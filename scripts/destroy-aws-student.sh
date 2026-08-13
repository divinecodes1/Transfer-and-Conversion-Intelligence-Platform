#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: tear down the AWS demo.
#
#   ./scripts/destroy-aws-student.sh
#
# The most important cost control in the repository. A free tier is finite and a
# stack left running over a holiday is the usual way it disappears, so
# destroying has to be as easy as deploying.
#
# Nothing here is precious: the warehouse rebuilds from sql/ and the generator
# in about a minute, the realm re-imports, and the infrastructure is Terraform.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/aws"
BOOT_DIR="${TF_DIR}/bootstrap"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

command -v terraform >/dev/null 2>&1 || die "terraform is not installed."
command -v aws >/dev/null 2>&1 || die "aws is not installed."
aws sts get-caller-identity >/dev/null 2>&1 || die "Not authenticated. Run: aws configure"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

cd "${TF_DIR}"
[[ -f terraform.tfstate || -d .terraform ]] \
  || die "No Terraform state here. Either nothing is deployed, or wrong checkout."

terraform init -input=false >/dev/null
REGION="$(terraform output -raw region 2>/dev/null || echo unknown)"

printf '\n'
bold "This will permanently delete, in account ${ACCOUNT_ID} (${REGION}):"
printf '\n'
warn "  - the RDS instance and BOTH databases (warehouse and Keycloak)"
warn "  - the Keycloak EC2 instance and its realm state"
warn "  - every registered Keycloak user"
warn "  - both S3 buckets: the console, and all documents/reports/exports"
warn "  - the CloudFront distribution (a new deploy gets a new hostname)"
warn "  - both ECR repositories and every image in them (bootstrap stage)"
warn "  - the IAM role GitHub Actions assumes"
printf '\n'
info "Reproducible from this repository: the warehouse, the realm, the console"
info "and the whole infrastructure. Anything typed into the running system is not."
printf '\n'

# Shown from AWS rather than from state, so a resource Terraform lost track of
# is still visible before it goes.
bold "Currently deployed:"
terraform state list 2>/dev/null | sed 's/^/    /' | head -40
printf '\n'

read -r -p "Type 'destroy' to confirm: " confirmation
[[ "${confirmation}" == "destroy" ]] || die "Not confirmed. Nothing was deleted."

printf '\n'
bold "==> Destroying"

# Buckets and ECR repositories are created with force_destroy / force_delete, so
# a non-empty bucket does not stall the teardown -- the single most common way a
# `terraform destroy` half-completes and leaves things billing.
terraform destroy -input=false -auto-approve

# ECR is a separate state so it can exist before the first Lambda is created.
# It must therefore be destroyed second, after no function references its image.
if [[ -d "${BOOT_DIR}/.terraform" || -f "${BOOT_DIR}/terraform.tfstate" ]]; then
  terraform -chdir="${BOOT_DIR}" init -input=false >/dev/null
  terraform -chdir="${BOOT_DIR}" destroy -input=false -auto-approve
fi

printf '\n'
bold "==> Checking for anything left behind"

# Terraform destroys what it created. Something added by hand, or left by a
# partial apply, would survive and keep billing -- which is the outcome this
# script exists to prevent.
LEFTOVERS=0

check() {
  local label="$1" count="$2"
  if [[ "${count}" != "0" && -n "${count}" && "${count}" != "None" ]]; then
    warn "${label}: ${count}"
    LEFTOVERS=1
  fi
}

check "EC2 instances still running" \
  "$(aws ec2 describe-instances --region "${REGION}" \
     --filters "Name=tag:project,Values=transfer-intelligence" "Name=instance-state-name,Values=running,pending,stopping,stopped" \
     --query "length(Reservations[].Instances[])" --output text 2>/dev/null || echo 0)"

check "RDS instances" \
  "$(aws rds describe-db-instances --region "${REGION}" \
     --query "length(DBInstances[?starts_with(DBInstanceIdentifier,'ti-')])" --output text 2>/dev/null || echo 0)"

check "Elastic IPs (billed while unattached)" \
  "$(aws ec2 describe-addresses --region "${REGION}" \
     --query "length(Addresses[?AssociationId==null])" --output text 2>/dev/null || echo 0)"

check "EBS volumes (survive their instance)" \
  "$(aws ec2 describe-volumes --region "${REGION}" \
     --filters "Name=status,Values=available" \
     --query "length(Volumes[])" --output text 2>/dev/null || echo 0)"

check "RDS snapshots" \
  "$(aws rds describe-db-snapshots --region "${REGION}" --snapshot-type manual \
     --query "length(DBSnapshots[])" --output text 2>/dev/null || echo 0)"

printf '\n'
if [[ "${LEFTOVERS}" -eq 0 ]]; then
  bold "==> Clean"
  info "Nothing chargeable remains in ${REGION}."
else
  bold "==> Review the warnings above"
  warn "An unattached Elastic IP and an available EBS volume both bill while"
  warn "doing nothing, and neither shows up as a 'running' resource."
fi

printf '\n'
info "Confirm for yourself:  aws resourcegroupstaggingapi get-resources \\"
info "                         --tag-filters Key=project,Values=transfer-intelligence \\"
info "                         --region ${REGION}"
info "Redeploy any time:     ./scripts/deploy-aws-student.sh"
printf '\n'
