#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOT="$ROOT/infrastructure/aws/bootstrap"
APP="$ROOT/infrastructure/aws"
REGION_INPUT="${TF_VAR_region:-eu-central-1}"
PREFIX_INPUT="${TF_VAR_prefix:-ti}"
ENVIRONMENT_INPUT="${TF_VAR_environment:-student}"
step(){ printf '\n==> %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

for tool in aws terraform docker node npm; do command -v "$tool" >/dev/null || die "$tool is required"; done
aws sts get-caller-identity >/dev/null || die "Authenticate first with aws configure or aws sso login"
docker info >/dev/null || die "Docker Desktop is not running"

step "Detecting the current AWS account plan"
if PLAN="$(aws freetier get-account-plan-state --region us-east-1 --query '[accountPlanType,accountPlanStatus,accountPlanRemainingCredits.amount,accountPlanExpirationDate]' --output text)"; then
  read -r PLAN_TYPE PLAN_STATUS PLAN_CREDITS PLAN_EXPIRY <<<"$PLAN"
  printf '  Type: %s  Status: %s  Credits: %s USD  Expires: %s\n' "$PLAN_TYPE" "$PLAN_STATUS" "$PLAN_CREDITS" "$PLAN_EXPIRY"
  if { [[ "$PLAN_TYPE" != "FREE" ]] || [[ "$PLAN_STATUS" != "ACTIVE" ]]; } && [[ "${TRANSFEROPS_ALLOW_PAID:-false}" != "true" ]]; then
    die "Free Plan is not active. Set TRANSFEROPS_ALLOW_PAID=true only if paid deployment is intentional."
  fi
else
  printf 'WARNING: the account-plan API was unavailable; verify Billing > Free Tier before continuing.\n'
fi

step "Stage 1/2: creating ECR repositories"
terraform -chdir="$BOOT" init -input=false
terraform -chdir="$BOOT" apply -input=false -auto-approve \
  -var="region=$REGION_INPUT" -var="prefix=$PREFIX_INPUT" -var="environment=$ENVIRONMENT_INPUT"
REGION="$(terraform -chdir="$BOOT" output -raw region)"
API_REPO="$(terraform -chdir="$BOOT" output -raw api_repository_url)"
KC_REPO="$(terraform -chdir="$BOOT" output -raw keycloak_repository_url)"

step "Building and pushing deployable images"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${API_REPO%%/*}"
docker build -t transfer-intelligence:base "$ROOT"
docker build -f "$ROOT/infrastructure/docker/lambda/Dockerfile" --build-arg BASE_IMAGE=transfer-intelligence:base -t "$API_REPO:latest" "$ROOT"
docker build -f "$ROOT/infrastructure/docker/keycloak/Dockerfile" -t "$KC_REPO:latest" "$ROOT"
docker push "$API_REPO:latest"
docker push "$KC_REPO:latest"

# The IAM OIDC provider and the CI deployment role are only created when
# github_repository is set -- and when it is not, nothing fails. The apply
# succeeds, the stack works, and CI simply has no role to assume, which is not
# discovered until setup-github-actions.sh cannot find one. Resolve it here.
step "Resolving the repository allowed to deploy from CI"
tfvars_repository() {
  [[ -f "$APP/terraform.tfvars" ]] || return 0
  sed -n 's/^[[:space:]]*github_repository[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$APP/terraform.tfvars" | head -1
}
if [[ -n "${TF_VAR_github_repository:-}" ]]; then
  printf '  %s (from TF_VAR_github_repository)\n' "$TF_VAR_github_repository"
elif [[ -n "$(tfvars_repository)" ]]; then
  printf '  %s (from terraform.tfvars)\n' "$(tfvars_repository)"
elif command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  TF_VAR_github_repository="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
  export TF_VAR_github_repository
  printf '  %s (detected with gh)\n' "$TF_VAR_github_repository"
else
  printf 'WARNING: github_repository is not set and gh is unavailable.\n'
  printf '         The stack will deploy, but GitHub Actions will have no role to assume.\n'
  printf '         Add to %s/terraform.tfvars and re-run:\n' "$APP"
  printf '           github_repository = "owner/name"\n'
fi

step "Stage 2/2: creating private application resources"
terraform -chdir="$APP" init -input=false
terraform -chdir="$APP" apply -input=false -auto-approve \
  -var="region=$REGION_INPUT" -var="prefix=$PREFIX_INPUT" -var="environment=$ENVIRONMENT_INPUT"

API_URL="$(terraform -chdir="$APP" output -raw api_url)"
AGENT_URL="$(terraform -chdir="$APP" output -raw assistant_url)"
KC_URL="$(terraform -chdir="$APP" output -raw keycloak_url)"
INSTANCE="$(terraform -chdir="$APP" output -raw keycloak_instance_id)"
ROLLOUT_DOC="$(terraform -chdir="$APP" output -raw keycloak_rollout_document)"
SEED_DOC="$(terraform -chdir="$APP" output -raw warehouse_seed_document)"

step "Waiting for the managed Keycloak host"
for attempt in $(seq 1 60); do
  ONLINE="$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)"
  [[ "$ONLINE" == "Online" ]] && break
  [[ "$attempt" == 60 ]] && die "SSM did not report $INSTANCE online"
  sleep 10
done

run_ssm(){
  local document="$1" parameters="$2"
  local command_id
  command_id="$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name "$document" --parameters "$parameters" --query 'Command.CommandId' --output text)"
  aws ssm wait command-executed --region "$REGION" --command-id "$command_id" --instance-id "$INSTANCE"
  aws ssm get-command-invocation --region "$REGION" --command-id "$command_id" --instance-id "$INSTANCE" --query '{Status:Status,Output:StandardOutputContent}' --output table
}

step "Rolling Keycloak through SSM"
run_ssm "$ROLLOUT_DOC" "ImageUri=$KC_REPO:latest,PublicUrl=$KC_URL"

step "Loading the private warehouse through SSM"
OPERATOR="${TRANSFEROPS_OPERATOR:-}"
SEED_PARAMETERS="ImageUri=$API_REPO:latest"
[[ -n "$OPERATOR" ]] && SEED_PARAMETERS="$SEED_PARAMETERS,Operator=$OPERATOR"
run_ssm "$SEED_DOC" "$SEED_PARAMETERS"

step "Building and publishing the console"
BUCKET="$(terraform -chdir="$APP" output -raw console_bucket)"
DIST="$(terraform -chdir="$APP" output -raw cloudfront_distribution_id)"
CONSOLE_URL="$(terraform -chdir="$APP" output -raw console_url)"
(cd "$ROOT/web" && npm ci && VITE_TRANSFEROPS_API="$API_URL" VITE_TRANSFEROPS_AGENT="$AGENT_URL" VITE_KEYCLOAK_URL="$KC_URL" VITE_KEYCLOAK_REALM=transferops VITE_KEYCLOAK_CLIENT_ID=transferops-api VITE_TRANSFEROPS_AUTH=enforce npm run build)
aws s3 sync "$ROOT/web/dist" "s3://$BUCKET" --delete --exclude index.html --cache-control 'public,max-age=31536000,immutable'
aws s3 cp "$ROOT/web/dist/index.html" "s3://$BUCKET/index.html" --cache-control 'no-cache,must-revalidate'
aws cloudfront create-invalidation --distribution-id "$DIST" --paths '/*' >/dev/null

step "Deployment complete"
printf 'Console:   %s\nAPI:       %s\nAssistant: %s\nKeycloak:  %s\n' "$CONSOLE_URL" "$API_URL" "$AGENT_URL" "$KC_URL"
terraform -chdir="$APP" output -raw cost_posture

# This script exists to create the stack once. Every deployment after this one
# should come from CI, which needs the outputs above published to the
# repository -- that is the next command, and it is not optional if you want
# `git push` to deploy.
printf '\n\nHand the deployment over to GitHub Actions:\n'
printf '  ./scripts/setup-github-actions.sh\n'
printf '  gh workflow run deploy.yml\n\n'
