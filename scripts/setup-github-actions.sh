#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: wire GitHub Actions to AWS.
#
#   ./scripts/setup-github-actions.sh
#
# Reads the deployed stack from `terraform output` and pushes every secret and
# variable the workflows need. Nothing is copied by hand.
#
# THE ROLE ALREADY EXISTS. Terraform creates the IAM OIDC provider and the
# deployment role (infrastructure/aws/github_oidc.tf), because on AWS both live
# inside the account and need no administrator beyond the one deploying.
#
# That is the difference from the Azure attempt, which ended here: federated
# login there needed an Entra app registration, the university tenant set
# allowedToCreateApps=false, and no amount of subscription ownership helped --
# ARM rights and directory rights are separate. On AWS there is no directory in
# the way, so CI can actually deploy.
#
# No access key is created. GitHub mints a short-lived OIDC token scoped to this
# repository and the production-demo environment; the role's trust policy accepts
# exactly that.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/aws"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n'; bold "==> $*"; }

# ---- 1. Prerequisites -------------------------------------------------------
step "Checking prerequisites"

for tool in aws gh terraform; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed."
done
aws sts get-caller-identity >/dev/null 2>&1 || die "Not authenticated to AWS."
gh auth status >/dev/null 2>&1 || die "Not logged in to GitHub. Run: gh auth login"

GH_REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
info "Repository ${GH_REPO}"

# ---- 2. Read the deployment -------------------------------------------------
step "Reading terraform outputs"

cd "${TF_DIR}"
[[ -d .terraform ]] || die "Terraform is not initialised. Deploy first."

tf() { terraform output -raw "$1" 2>/dev/null || true; }

ROLE_ARN="$(tf github_actions_role_arn)"
REGION="$(tf region)"
API_URL="$(tf api_url)"
ASSISTANT_URL="$(tf assistant_url)"
CONSOLE_URL="$(tf console_url)"
KEYCLOAK_URL="$(tf keycloak_url)"
CONSOLE_BUCKET="$(tf console_bucket)"
DIST_ID="$(tf cloudfront_distribution_id)"
API_FN="$(tf api_function_name)"
REFRESH_FN="$(tf refresh_function_name)"
ASSISTANT_FN="$(tf assistant_function_name)"
KEYCLOAK_INSTANCE="$(tf keycloak_instance_id)"
KEYCLOAK_ROLLOUT_DOCUMENT="$(tf keycloak_rollout_document)"
WAREHOUSE_SEED_DOCUMENT="$(tf warehouse_seed_document)"

# ECR repository names, not URLs: amazon-ecr-login supplies the registry host.
API_REPO="$(basename "$(tf ecr_api_repository)")"
KC_REPO="$(basename "$(tf ecr_keycloak_repository)")"

cd "${REPO_ROOT}"

if [[ -z "${ROLE_ARN}" ]]; then
  warn "No github_actions_role_arn output."
  warn "Set github_repository in infrastructure/aws/terraform.tfvars and re-apply:"
  warn "  github_repository = \"${GH_REPO}\""
  die "Cannot wire CI without the role."
fi

info "Role   ${ROLE_ARN}"
info "Region ${REGION}"

# ---- 3. Secrets -------------------------------------------------------------
step "GitHub secrets"

set_secret() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then warn "skip    ${name} (no value)"; return; fi
  printf '%s' "${value}" | gh secret set "${name}" --repo "${GH_REPO}" >/dev/null
  info "set     ${name}"
}

# The role ARN is not a credential -- it names a role, and only a token from
# this repository can assume it. It is a secret here purely to keep the account
# id out of public logs.
set_secret AWS_ROLE_ARN                    "${ROLE_ARN}"
set_secret AWS_ECR_API_REPOSITORY          "${API_REPO}"
set_secret AWS_ECR_KEYCLOAK_REPOSITORY     "${KC_REPO}"
set_secret AWS_API_FUNCTION                "${API_FN}"
set_secret AWS_REFRESH_FUNCTION            "${REFRESH_FN}"
set_secret AWS_ASSISTANT_FUNCTION          "${ASSISTANT_FN}"
set_secret AWS_KEYCLOAK_INSTANCE           "${KEYCLOAK_INSTANCE}"
set_secret AWS_KEYCLOAK_ROLLOUT_DOCUMENT   "${KEYCLOAK_ROLLOUT_DOCUMENT}"
# RDS is private, so CI loads the warehouse by running this fixed document on
# the in-VPC host. Without it a schema change never reaches the deployment.
set_secret AWS_WAREHOUSE_SEED_DOCUMENT     "${WAREHOUSE_SEED_DOCUMENT}"
set_secret AWS_CONSOLE_BUCKET              "${CONSOLE_BUCKET}"
set_secret AWS_CLOUDFRONT_DISTRIBUTION_ID  "${DIST_ID}"

# ---- 4. Variables -----------------------------------------------------------
step "GitHub variables (public; VITE_* compile into the browser bundle)"

set_var() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then warn "skip    ${name} (no value)"; return; fi
  gh variable set "${name}" --repo "${GH_REPO}" --body "${value}" >/dev/null
  info "set     ${name} = ${value}"
}

set_var AWS_REGION       "${REGION}"
set_var AWS_API_URL      "${API_URL}"
set_var AWS_ASSISTANT_URL "${ASSISTANT_URL}"
set_var AWS_CONSOLE_URL  "${CONSOLE_URL}"
set_var AWS_KEYCLOAK_URL "${KEYCLOAK_URL}"

# Compiled into the bundle and therefore PUBLIC. Only values safe to publish
# appear here; tests/web_checks.py asserts the built console holds no key.
set_var VITE_TRANSFEROPS_API    "${API_URL}"
set_var VITE_TRANSFEROPS_AGENT  "${ASSISTANT_URL}"
set_var VITE_KEYCLOAK_URL       "${KEYCLOAK_URL}"
set_var VITE_KEYCLOAK_REALM     "transferops"
set_var VITE_KEYCLOAK_CLIENT_ID "transferops-api"
set_var VITE_TRANSFEROPS_AUTH   "oidc"

# The switch the deploy jobs read. A repository VARIABLE, not a secret: a
# job-level `if:` cannot see the secrets context, so a secret could never gate
# a job even though it looks like it should.
set_var AWS_DEPLOY_ENABLED "true"

# Optional. A warehouse reload rebuilds tr_gov, which drops the entitlements
# granted to accounts registered since the last load -- including yours, leaving
# a console that is correctly enforcing an empty scope. Naming the demo account
# here re-grants it as part of the same load.
#
#   TRANSFEROPS_OPERATOR=you@example.com ./scripts/setup-github-actions.sh
if [[ -n "${TRANSFEROPS_OPERATOR:-}" ]]; then
  set_var TRANSFEROPS_OPERATOR "${TRANSFEROPS_OPERATOR}"
else
  warn "skip    TRANSFEROPS_OPERATOR (set it to keep your account entitled across a warehouse reload)"
fi

# ---- 5. Summary -------------------------------------------------------------
step "Done"

cat <<SUMMARY

  CI assumes        ${ROLE_ARN}
  Authentication    federated OIDC -- NO access key exists
  Scoped to         repo:${GH_REPO}:environment:production-demo
                    repo:${GH_REPO}:ref:refs/heads/main

  Create the environment the deploy jobs declare, if it does not exist:
    GitHub -> Settings -> Environments -> New environment -> production-demo

  Verify:
    gh secret list --repo ${GH_REPO}
    gh variable list --repo ${GH_REPO}

  Deploy everything, in order, and verify all three tiers:
    gh workflow run deploy.yml

  Force a warehouse reload with it (drops entitlements granted since the last
  load; TRANSFEROPS_OPERATOR above is re-granted automatically):
    gh workflow run deploy.yml -f seed_warehouse=true

  Or let a push do it. backend.yml and frontend.yml run on their own paths, and
  backend.yml reloads the warehouse by itself whenever sql/ or etl/ changed.

SUMMARY
