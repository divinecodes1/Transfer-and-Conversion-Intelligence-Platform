"""
Transfer & Conversion Intelligence Platform :: the layered ingestion path.

    CSV  ->  tr_raw  ->  [ingestion checks]  ->  tr_stg  ->  tr_core
                                                          -> [core checks]
                                                          -> [metric checks]

`etl/run.py` is the fast path: it bulk-loads straight into CORE, and is what a
production deployment would use for a full refresh. This is the *layered* path,
and it exists to make two things real rather than described:

  1. **RAW is separable from meaning.** When a number is disputed, "did the source
     send it wrong or did we transform it wrong?" is answered by diffing two
     layers instead of by argument.
  2. **A bad row is quarantined, not fatal.** One malformed record from an
     upstream system should cost you that record, not the portfolio.

Idempotence is a property, not a hope: a record is identified by the content hash
of its business payload, so redelivering unchanged data collapses to the same
staged rows rather than doubling the portfolio. Re-running is a no-op, which is
the only way a pipeline is safe to retry -- and retryability is what makes
backfills possible.

Runs on both engines:

    python etl/ingest.py                                  # DuckDB
    python etl/ingest.py --corrupt                        # watch quarantine work
    python etl/ingest.py --engine postgres --dsn ...      # PostgreSQL
"""
import argparse
import csv
import hashlib
import os
import uuid

import credentials
from dq_checks import (CORE, INGESTION, METRIC, rejected_keys, report,
                       run_tier)
from engine import DUCKDB, POSTGRES, Engine

HERE = os.path.dirname(__file__)
SQL_DIR = os.path.join(HERE, "..", "sql")
DATA_DIR = os.path.join(HERE, "..", "data")

# csv file -> (raw table, source system)
FEEDS = {
    "dim_project.csv":            ("tr_raw.raw_project",   "PROJECT_MASTER"),
    "fact_schedule_revision.csv": ("tr_raw.raw_schedule",  "SCHEDULE_SYSTEM"),
    "fact_milestone_event.csv":   ("tr_raw.raw_milestone", "MILESTONE_TRACKER"),
    "fact_project_snapshot.csv":  ("tr_raw.raw_snapshot",  "SNAPSHOT_FEED"),
}

# Loaded straight to core: reference data with no meaningful source history.
REFERENCE = {
    "dim_milestone.csv":   "tr_core.dim_milestone",
    "dim_fiscal_date.csv": "tr_core.dim_fiscal_date",
}

META = ["source_system", "source_record_id", "ingested_at", "batch_id", "record_hash"]

SCHEMA_FILES = ["00_schemas.sql", "01_core_tables.sql", "02_governance.sql",
                "05_raw_tables.sql"]
POST_FILES = ["03_metric_views.sql", "04_marts.sql", "09_entitlements.sql"]
# PostgreSQL-only, and NOT optional: 01_core_tables.sql drops dim_project, which
# takes its row-level policy with it. A layered load that skipped these would
# leave the warehouse loaded and silently unprotected -- the worst of both.
POST_FILES_PG = ["07_indexes.sql", "10_rls.sql", "11_observability.sql"]


def read_sql(fname):
    with open(os.path.join(SQL_DIR, fname), encoding="utf-8") as f:
        return f.read()


def row_hash(row, cols):
    """Content hash of the business payload -- metadata deliberately excluded, so
    the same record redelivered in a new batch hashes identically."""
    payload = "|".join(str(row.get(c, "")) for c in cols)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def land(con, csv_name, table, source_system, batch_id, corrupt=False):
    """Load one feed into RAW with full source metadata."""
    path = os.path.join(DATA_DIR, csv_name)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        cols = list(rows[0].keys()) if rows else []

    if corrupt and table == "tr_raw.raw_project":
        rows = corrupt_batch(rows)

    target = META + cols
    sql = (f"INSERT INTO {table} ({', '.join(target)}) "
           f"VALUES ({', '.join('?' for _ in target)})")
    con.executemany(sql, [
        [source_system, r.get("project_key", str(i)), None, batch_id,
         row_hash(r, cols)] + [r.get(c) for c in cols]
        for i, r in enumerate(rows)])
    con.execute(f"UPDATE {table} SET ingested_at = CURRENT_TIMESTAMP "
                f"WHERE batch_id = ? AND ingested_at IS NULL", [batch_id])
    return len(rows)


def corrupt_batch(rows):
    """
    Inject the failure modes a real feed actually produces.

    Not to make the demo dramatic -- to prove the tiers catch the right thing at
    the right layer, and that the clean majority still lands.
    """
    return rows + [
        {**rows[0], "project_key": "9001", "project_id": "T-BAD1",
         "actual_start": "2026-13-45"},                      # unparseable date
        {**rows[1], "project_key": "9002", "project_id": "T-BAD2",
         "status": "IN_PROGRESS"},                           # outside the domain
        {**rows[2], "project_key": "9003", "project_id": "T-BAD3",
         "portfolio": ""},                                   # mandatory field empty
        {**rows[3]},                                         # duplicate key
    ]


def promote(con, rejected=()):
    """
    STAGING -> CORE. The only place typed data becomes canonical.

    Rows rejected at the ingestion tier are held back here, which is what makes
    "quarantined" mean something. Only REJECT-severity findings block: a duplicate
    delivery is a WARN because staging already resolves it deterministically, and
    dropping that project would lose good data over a problem already handled.
    """
    keys = [str(int(k)) for k in rejected if str(k).lstrip("-").isdigit()]
    key_filter = f" AND project_key NOT IN ({', '.join(keys)})" if keys else ""

    con.execute(f"""
        INSERT INTO tr_core.dim_project
        SELECT project_key, project_id, project_name, transfer_type,
               complexity_class, source_site, target_site, portfolio, status,
               actual_start, actual_finish
        FROM tr_stg.stg_project
        WHERE status IN ('COMPLETED', 'ACTIVE', 'PLANNED', 'CANCELLED')
        {key_filter}
    """)
    con.execute("""
        INSERT INTO tr_core.fact_schedule_revision
        SELECT project_key, revision_id, revision_timestamp, revision_reason,
               planned_start, planned_finish, forecast_finish, is_baseline
        FROM tr_stg.stg_schedule
        WHERE project_key IN (SELECT project_key FROM tr_core.dim_project)
    """)
    con.execute("""
        INSERT INTO tr_core.fact_milestone_event
        SELECT project_key, milestone_key, planned_date, actual_date, event_status
        FROM tr_stg.stg_milestone
        WHERE project_key IN (SELECT project_key FROM tr_core.dim_project)
    """)
    con.execute("""
        INSERT INTO tr_core.fact_project_snapshot
        SELECT project_key, snapshot_date, status, forecast_finish,
               current_stage, risk_status, progress_pct
        FROM tr_stg.stg_snapshot
        WHERE project_key IN (SELECT project_key FROM tr_core.dim_project)
    """)


def ingest(db_path=None, corrupt=False, batch_id=None, verbose=True,
           engine=DUCKDB, dsn=None):
    """Run the full layered pipeline. Returns (Engine, summary dict)."""
    batch_id = batch_id or f"batch-{uuid.uuid4().hex[:8]}"
    con = (Engine.postgres(dsn) if engine == POSTGRES
           else Engine.duckdb(db_path))

    if engine == POSTGRES:
        # 10_rls.sql and 11_observability.sql create the least-privilege login
        # roles and read their passwords from these settings, never from the SQL.
        credentials.apply(lambda sql, params: con.execute(sql.replace("%s", "?"), params),
                          dsn, warn=(print if verbose else lambda *_a: None))

    for fn in SCHEMA_FILES:
        con.script(read_sql(fn))
    # The safe-cast shim the staging views depend on, per engine.
    con.script(read_sql("06_functions_postgres.sql" if engine == POSTGRES
                        else "06_functions_duckdb.sql"))
    con.script(read_sql("06_staging.sql"))

    if verbose:
        print(f"Batch {batch_id}  ({engine})")
        print("-" * 70)

    landed = 0
    for csv_name, (table, system) in FEEDS.items():
        landed += land(con, csv_name, table, system, batch_id, corrupt=corrupt)
    for csv_name, table in REFERENCE.items():
        con.load_csv(table, os.path.abspath(os.path.join(DATA_DIR, csv_name)))
    if verbose:
        print(f"  landed {landed:,} rows into tr_raw")

    # ---- tier 1: is the delivery usable at all? --------------------------
    ing = run_tier(con, "INGESTION", INGESTION, batch_id=batch_id)
    blocked = rejected_keys(con, batch_id)
    if verbose:
        flagged = report(ing, "INGESTION")
        print(f"  {flagged} finding(s) quarantined; {len(blocked)} row(s) held back "
              f"from CORE, the clean majority continues")

    promote(con, rejected=blocked)
    for fn in POST_FILES + (POST_FILES_PG if engine == POSTGRES else []):
        con.script(read_sql(fn))

    # ---- tiers 2 and 3: is the model coherent, and does the metric layer
    #      agree with it? --------------------------------------------------
    core = run_tier(con, "CORE", CORE, batch_id=batch_id)
    metric = run_tier(con, "METRIC", METRIC, batch_id=batch_id)
    if verbose:
        report(core, "CORE")
        report(metric, "METRIC")

    n_core = con.execute("SELECT COUNT(*) FROM tr_core.dim_project").fetchone()[0]
    n_quar = con.execute("SELECT COUNT(*) FROM tr_raw.quarantine").fetchone()[0]
    if verbose:
        print("-" * 70)
        print(f"  {n_core} projects in tr_core.dim_project, {n_quar} quarantined rows\n")

    return con, {"batch_id": batch_id, "engine": engine, "landed": landed,
                 "core_projects": n_core, "quarantined": n_quar,
                 "ingestion_failures": ing, "core_failures": core,
                 "metric_failures": metric}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=[DUCKDB, POSTGRES], default=DUCKDB)
    ap.add_argument("--db", default=os.path.join(HERE, "..", "warehouse_layered.duckdb"))
    ap.add_argument("--dsn", default=os.environ.get(
        "TRANSFEROPS_DSN", "postgresql://app:dev@localhost:5432/transferops"))
    ap.add_argument("--corrupt", action="store_true",
                    help="inject malformed rows to demonstrate quarantine")
    args = ap.parse_args()
    con, summary = ingest(args.db, corrupt=args.corrupt, engine=args.engine,
                          dsn=args.dsn)
    con.close()
    return summary


if __name__ == "__main__":
    main()
