#!/usr/bin/env bash
# ============================================================================
# Transfer & Conversion Intelligence Platform :: seed the deployed warehouse.
#
#   ./scripts/seed-demo-data.sh              # against the AWS deployment
#   ./scripts/seed-demo-data.sh --local      # against docker compose
#
# Generates the synthetic portfolio and runs the same loader the local build
# uses, so the cloud warehouse is byte-identical to the one the golden gate
# asserts against. There is no separate "cloud seeding" path, because a second
# path is a second set of numbers.
#
# The data is synthetic and is never presented as Infineon's. See §55 of the
# master plan and the disclaimer the console renders.
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/infrastructure/aws"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

LOCAL=false
[[ "${1:-}" == "--local" ]] && LOCAL=true

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON not found. Set PYTHON=..."

cd "${REPO_ROOT}"

if $LOCAL; then
  bold "==> Seeding the local compose warehouse"
  DSN="${TRANSFEROPS_DSN:-postgresql://app:dev@localhost:5432/transferops}"
  export TRANSFEROPS_READER_PASSWORD="${TRANSFEROPS_READER_PASSWORD:-reader}"
  export TRANSFEROPS_AUDITOR_PASSWORD="${TRANSFEROPS_AUDITOR_PASSWORD:-auditor}"
  export TRANSFEROPS_AI_PASSWORD="${TRANSFEROPS_AI_PASSWORD:-ai}"
else
  bold "==> Seeding the AWS warehouse"
  command -v terraform >/dev/null 2>&1 || die "terraform is not installed."
  [[ -d "${TF_DIR}/.terraform" ]] || die "Terraform is not initialised. Deploy first."

  # Passwords come from state and are piped straight into the loader. They are
  # never echoed and never written to a file.
  DSN="$(terraform -chdir="${TF_DIR}" output -raw loader_dsn)" \
    || die "Could not read loader_dsn. Has the stack been deployed?"
  export TRANSFEROPS_READER_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw reader_password)"
  export TRANSFEROPS_AUDITOR_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw auditor_password)"
  export TRANSFEROPS_AI_PASSWORD="$(terraform -chdir="${TF_DIR}" output -raw ai_password)"

  warn "This drops and rebuilds every table in tr_core, tr_metric and tr_mart."
  warn "tr_gov.etl_run and tr_gov.agent_audit survive by design."
fi

bold "==> Generating the synthetic portfolio"
"$PYTHON" etl/generate_data.py

bold "==> Loading, with data-quality gates"
# A failing gate exits non-zero and takes this script with it. Seeding a
# warehouse that did not reconcile would put numbers on a dashboard that no
# test stands behind.
"$PYTHON" etl/run.py --engine postgres --dsn "$DSN"

bold "==> Verifying"
export SEED_DSN="$DSN"
"$PYTHON" - <<'PY'
import os, psycopg2
dsn = os.environ["SEED_DSN"]
with psycopg2.connect(dsn) as con, con.cursor() as cur:
    cur.execute("SELECT set_config('transferops.portfolios', '*', false)")
    for label, query in [
        ("projects",   "SELECT COUNT(*) FROM tr_core.dim_project"),
        ("milestones", "SELECT COUNT(*) FROM tr_core.fact_milestone_event"),
        ("readiness",  "SELECT COUNT(*) FROM tr_core.fact_readiness_assessment"),
        ("metrics",    "SELECT COUNT(*) FROM tr_gov.metric_definition"),
        ("lanes",      "SELECT COUNT(*) FROM tr_mart.mart_transfer_network"),
    ]:
        cur.execute(query)
        print(f"  {label:<12} {cur.fetchone()[0]}")
PY

printf '\n'
bold "==> Seeded"
info "Synthetic data only. Never present it as real Infineon data."
printf '\n'
