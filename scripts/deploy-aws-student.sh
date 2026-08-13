#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: AWS student deployment.
#
#   ./scripts/deploy-aws-student.sh
#
# From an empty AWS account to a working public demo. Everything is Terraform or
# the AWS CLI; there is no step that says "now open the console and click",
# because a step like that is a step nobody can repeat.
#
# Safe to re-run.
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

for tool in aws terraform docker python3; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed or not on PATH."
done

aws sts get-caller-identity >/dev/null 2>&1 \
  || die "Not authenticated. Run: aws configure  (or aws sso login)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
CALLER="$(aws sts get-caller-identity --query Arn --output text)"
info "Account ${ACCOUNT_ID}"
info "Caller  ${CALLER}"

docker info >/dev/null 2>&1 || die "Docker is not running."

# ---- 2. Which free tier? ----------------------------------------------------
step "Free tier"

# The single biggest cost fact, and the console does not surface it in an
# obvious place. Best effort: the API is not available in every account.
if aws freetier get-free-tier-usage --region us-east-1 >/dev/null 2>&1; then
  USED="$(aws freetier get-free-tier-usage --region us-east-1 \
    --query "length(freeTierUsages)" --output text 2>/dev/null || echo 0)"
  info "Free-tier usage records: ${USED}"
  info "A non-zero count means the legacy 12-month tier applies -- RDS and EC2"
  info "are free for 750h/month and this stack costs essentially nothing."
else
  warn "Could not read free-tier usage (the API is not enabled on every account)."
  warn "If you are on the newer credit-based tier there are no free service"
  warn "hours: expect roughly 20 USD/month, dominated by RDS and EC2."
  warn "Check: Billing console -> Free Tier."
fi

# ---- 3. Inputs --------------------------------------------------------------
step "Deployment inputs"

CLIENT_IP="${TRANSFEROPS_CLIENT_IP:-$(curl -fsS https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)}"
if [[ -n "${CLIENT_IP}" ]]; then
  export TF_VAR_allowed_client_ip="${CLIENT_IP}/32"
  info "Operator IP: ${CLIENT_IP}/32"
else
  warn "Could not detect your public IP; the loader will not reach the database."
fi

if [[ -z "${TF_VAR_ai_api_key:-}" ]]; then
  info "No TF_VAR_ai_api_key -- deploying with ai_provider=mock."
  info "Every AI surface still works; narratives are deterministic, not generated."
fi

if ! grep -qE '^\s*budget_alert_emails\s*=\s*\[\s*"' "${TF_DIR}/terraform.tfvars" 2>/dev/null \
   && [[ -z "${TF_VAR_budget_alert_emails:-}" ]]; then
  warn "No budget alert address configured."
  warn "AWS does not stop spending when a budget is exceeded -- the alert is the"
  warn "only early warning there is."
  read -r -p "  Email for budget alerts (blank to skip): " budget_email || true
  [[ -n "${budget_email:-}" ]] && export TF_VAR_budget_alert_emails="[\"${budget_email}\"]"
fi

# ---- 4. Provision -----------------------------------------------------------
step "Provisioning (this takes 10-15 minutes; RDS is the slow part)"

cd "${TF_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve

REGION="$(terraform output -raw region)"
API_REPO="$(terraform output -raw ecr_api_repository)"
KC_REPO="$(terraform output -raw ecr_keycloak_repository)"
API_FN="$(terraform output -raw api_function_name)"
REFRESH_FN="$(terraform output -raw refresh_function_name)"
CONSOLE_URL="$(terraform output -raw console_url)"
API_URL="$(terraform output -raw api_url)"
KEYCLOAK_URL="$(terraform output -raw keycloak_url)"
BUCKET="$(terraform output -raw console_bucket)"
DIST_ID="$(terraform output -raw cloudfront_distribution_id)"

cd "${REPO_ROOT}"

# ---- 5. Images --------------------------------------------------------------
step "Building and pushing images"

aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${API_REPO%%/*}"

info "base image"
docker build -t transfer-intelligence:base "${REPO_ROOT}"

info "API image (Lambda Web Adapter on top of the base)"
docker build -f "${REPO_ROOT}/infrastructure/docker/lambda/Dockerfile" \
  --build-arg BASE_IMAGE=transfer-intelligence:base \
  -t "${API_REPO}:latest" "${REPO_ROOT}"
docker push "${API_REPO}:latest"

info "Keycloak image (realm + themes baked in)"
docker build -f "${REPO_ROOT}/infrastructure/docker/keycloak/Dockerfile" \
  -t "${KC_REPO}:latest" "${REPO_ROOT}"
docker push "${KC_REPO}:latest"

# The functions were created pointing at a tag that did not exist yet, so this
# is the first real code they receive.
info "pointing the functions at the pushed image"
for fn in "${API_FN}" "${REFRESH_FN}"; do
  aws lambda update-function-code --function-name "${fn}" \
    --image-uri "${API_REPO}:latest" --region "${REGION}" >/dev/null
  aws lambda wait function-updated --function-name "${fn}" --region "${REGION}"
  info "  ${fn}"
done

# ---- 6. Warehouse -----------------------------------------------------------
step "Building the warehouse"

if [[ -n "${CLIENT_IP}" ]]; then
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
  warn "Skipped -- no operator IP. Run scripts/seed-demo-data.sh once reachable."
fi

# ---- 7. Console -------------------------------------------------------------
step "Publishing the console"

if [[ -d "${REPO_ROOT}/web/dist" ]]; then
  aws s3 sync "${REPO_ROOT}/web/dist" "s3://${BUCKET}" --delete \
    --exclude index.html --cache-control "public,max-age=31536000,immutable"
  aws s3 cp "${REPO_ROOT}/web/dist/index.html" "s3://${BUCKET}/index.html" \
    --cache-control "no-cache,must-revalidate"
  aws cloudfront create-invalidation --distribution-id "${DIST_ID}" \
    --paths "/index.html" >/dev/null
  info "published"
else
  warn "web/dist not found. Build it first:  cd web && npm run build"
fi

# ---- 8. Operator access -----------------------------------------------------
step "Granting the operator access"

# A verified account still holds no entitlement -- the platform working as
# designed, and the wall every first deployment hits.
OPERATOR="${TRANSFEROPS_OPERATOR:-}"
if [[ -n "${OPERATOR}" && -n "${CLIENT_IP}" ]]; then
  SEED_DSN="$(terraform -chdir="${TF_DIR}" output -raw loader_dsn)" \
  TRANSFEROPS_OPERATOR="${OPERATOR}" python3 - <<'PY'
import os, psycopg2
u = os.environ["TRANSFEROPS_OPERATOR"]
with psycopg2.connect(os.environ["SEED_DSN"]) as con, con.cursor() as cur:
    cur.execute("SELECT set_config('transferops.portfolios','*',false)")
    cur.execute("INSERT INTO tr_gov.app_user (username, display_name, email) "
                "VALUES (%s,%s,%s) ON CONFLICT (username) DO NOTHING", (u, u, u))
    cur.execute("INSERT INTO tr_gov.user_role (username, role_code) SELECT %s,'PLATFORM_ADMIN' "
                "WHERE NOT EXISTS (SELECT 1 FROM tr_gov.user_role WHERE username=%s "
                "AND role_code='PLATFORM_ADMIN')", (u, u))
    cur.execute("INSERT INTO tr_gov.data_entitlement (username,dimension_type,dimension_value,valid_from,valid_to) "
                "SELECT %s,'PORTFOLIO','*',DATE '2020-01-01',NULL WHERE NOT EXISTS "
                "(SELECT 1 FROM tr_gov.data_entitlement WHERE username=%s AND dimension_type='PORTFOLIO')", (u, u))
print(f"  {u} -> PLATFORM_ADMIN, all portfolios")
PY
  warn "sql/09_entitlements.sql drops these tables on reload -- add the grant"
  warn "there to make it survive a rebuild."
else
  warn "No operator granted. Set TRANSFEROPS_OPERATOR=<your-email> and re-run,"
  warn "or sign-in will stop at the 'account is verified' screen."
fi

warn "No SMTP relay, so Keycloak cannot send verification mail and"
warn "self-registration will not complete. The grant above is the way in."

# ---- 9. Summary -------------------------------------------------------------
step "Deployed"

cat <<SUMMARY

  Console   ${CONSOLE_URL}
  API       ${API_URL}          (Swagger at /docs)
  Keycloak  ${KEYCLOAK_URL}

  Keycloak takes a few minutes on first boot to pull its image and import the
  realm. Watch it with:
    aws ssm start-session --target $(terraform -chdir="${TF_DIR}" output -raw keycloak_instance_id)

  Credentials, on demand:
    terraform -chdir=infrastructure/aws output -raw keycloak_admin_password
    terraform -chdir=infrastructure/aws output -raw database_password

  Wire up CI:
    ./scripts/setup-github-actions.sh

  Standing cost:
$(terraform -chdir="${TF_DIR}" output -raw cost_posture | sed 's/^/    /')

  Tear it all down:
    ./scripts/destroy-aws-student.sh

SUMMARY
