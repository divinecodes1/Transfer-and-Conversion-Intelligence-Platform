"""
Transfer & Conversion Intelligence Platform :: build + load runner.

Usage:
    python etl/run.py --engine duckdb   [--db warehouse.duckdb]   # local, no server
    python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops

Executes sql/00..04 in order, loads the generated CSVs into tr_core, and leaves
a queryable warehouse. The SQL files are the single source of truth for both
engines (date math is portable). Data-quality checks run at the end.
"""
import argparse, csv, glob, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
# Named credentials, not secrets: a module called `secrets` on sys.path shadows
# the standard library module of that name for everything imported after it.
import credentials  # noqa: E402

SQL_DIR  = os.path.join(os.path.dirname(__file__), "..", "sql")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

CORE_TABLES = {
    "dim_project": "tr_core.dim_project",
    "dim_milestone": "tr_core.dim_milestone",
    "dim_fiscal_date": "tr_core.dim_fiscal_date",
    "dim_readiness_dimension": "tr_core.dim_readiness_dimension",
    "fact_schedule_revision": "tr_core.fact_schedule_revision",
    "fact_project_snapshot": "tr_core.fact_project_snapshot",
    "fact_milestone_event": "tr_core.fact_milestone_event",
    "fact_readiness_assessment": "tr_core.fact_readiness_assessment",
}

# statements that must run before data load (schemas + core tables) vs after.
PRELOAD = ["00_schemas.sql", "01_core_tables.sql", "02_governance.sql"]
# 13 must follow 03/04: readiness reads the register for the health band, and the
# network and similarity views read readiness.
POSTLOAD = ["03_metric_views.sql", "04_marts.sql", "13_readiness_network.sql",
            "09_entitlements.sql"]
# Row-level security is PostgreSQL-only; DuckDB is the dev/test engine and has no
# equivalent, so the entitlement *model* is portable and its *enforcement* is not.
POSTLOAD_PG = ["07_indexes.sql", "10_rls.sql", "11_observability.sql", "12_ai.sql"]


def read_sql(fname):
    with open(os.path.join(SQL_DIR, fname)) as f:
        return f.read()


def split_statements(sql):
    # strip full-line comments first, then split on ';'
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


# ----------------------------------------------------------------------------
def run_duckdb(db_path):
    import duckdb
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)
    for fn in PRELOAD:
        for stmt in split_statements(read_sql(fn)):
            con.execute(stmt)
    # load CSVs
    for csv_name, table in CORE_TABLES.items():
        path = os.path.join(DATA_DIR, f"{csv_name}.csv")
        con.execute(f"COPY {table} FROM '{path}' (HEADER, NULLSTR '')")
    for fn in POSTLOAD:
        for stmt in split_statements(read_sql(fn)):
            con.execute(stmt)
    return con


def run_postgres(dsn):
    import psycopg2
    con = psycopg2.connect(dsn)
    con.autocommit = True
    cur = con.cursor()
    # The loader is the one caller entitled to the whole portfolio. RLS is
    # fail-closed, so this has to be explicit -- and being explicit is the point:
    # a privileged scope is granted in one visible place rather than by default.
    cur.execute("SELECT set_config('transferops.portfolios', '*', false)")
    # Role credentials come from the environment, never from the SQL files.
    credentials.apply(lambda sql, params: cur.execute(sql, params), dsn)
    for fn in PRELOAD:
        cur.execute(read_sql(fn))
    for csv_name, table in CORE_TABLES.items():
        path = os.path.join(DATA_DIR, f"{csv_name}.csv")
        with open(path) as f:
            cur.copy_expert(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')", f)
    for fn in POSTLOAD + POSTLOAD_PG:
        cur.execute(read_sql(fn))
    return con


# ----------------------------------------------------------------------------
def data_quality(fetch):
    """Return list of (check, passed, detail)."""
    checks = []

    def one(sql):
        return fetch(sql)[0][0]

    checks.append(("cycle time never negative",
                   one("SELECT COUNT(*) FROM tr_metric.v_project_cycle_time WHERE actual_cycle_time_days < 0") == 0,
                   "0 negatives expected"))
    checks.append(("baseline exists for every project",
                   one("SELECT COUNT(*) FROM tr_core.dim_project p "
                       "LEFT JOIN tr_metric.v_baseline_schedule b USING(project_key) "
                       "WHERE b.project_key IS NULL") == 0,
                   "every project has an immutable baseline"))
    checks.append(("actual_finish >= actual_start",
                   one("SELECT COUNT(*) FROM tr_core.dim_project "
                       "WHERE actual_finish IS NOT NULL AND actual_start IS NOT NULL "
                       "AND actual_finish < actual_start") == 0,
                   "no time-travel"))
    checks.append(("completion variance only for completed",
                   one("SELECT COUNT(*) FROM tr_metric.v_completion_variance cv "
                       "JOIN tr_core.dim_project p USING(project_key) "
                       "WHERE p.status <> 'COMPLETED'") == 0,
                   "population guard holds"))
    # A weight set that sums to anything other than 100 still produces a
    # plausible-looking percentage, which is exactly why it is gated rather than
    # trusted: the readiness score would be wrong and would not look wrong.
    checks.append(("readiness weights sum to 100",
                   one("SELECT SUM(weight_pct) FROM tr_core.dim_readiness_dimension") == 100,
                   "the weighted mean has a valid denominator"))
    checks.append(("readiness scores are percentages",
                   one("SELECT COUNT(*) FROM tr_core.fact_readiness_assessment "
                       "WHERE score_pct < 0 OR score_pct > 100") == 0,
                   "0..100, so a band cannot be reached by an impossible score"))
    # Caught a real defect: assessments were dated from the wall clock while the
    # warehouse vintage is the newest snapshot, so readiness was recorded days
    # *after* the data it describes and the average assessment age came out
    # negative. Nothing else in the platform would have noticed.
    checks.append(("no readiness assessed after the data vintage",
                   one("SELECT COUNT(*) FROM tr_core.fact_readiness_assessment "
                       "WHERE assessed_on > "
                       "(SELECT data_as_of FROM tr_metric.v_data_vintage)") == 0,
                   "assessment age is never negative"))
    checks.append(("readiness covers in-flight projects only",
                   one("SELECT COUNT(*) FROM tr_core.fact_readiness_assessment a "
                       "JOIN tr_core.dim_project p USING(project_key) "
                       "WHERE p.status NOT IN ('ACTIVE','PLANNED')") == 0,
                   "no completed or cancelled project carries a readiness score"))
    # Partial coverage is the subtler failure: the weighted mean divides by the
    # weights it actually found, so a project missing its qualification row would
    # score high on the strength of the six dimensions that did arrive.
    checks.append(("every assessed project has every dimension",
                   one("SELECT COUNT(*) FROM ("
                       "  SELECT project_key FROM tr_metric.v_project_readiness_dimension"
                       "  GROUP BY project_key"
                       "  HAVING COUNT(*) <> (SELECT COUNT(*) FROM tr_core.dim_readiness_dimension)"
                       ") x") == 0,
                   "no project is scored on a partial weight set"))
    return checks


def record_run(con, engine, started, n_rows, passed, failed):
    """
    Write one row of pipeline history.

    "Last successful load" and "load duration" are the first things anyone asks
    when a dashboard looks wrong, and neither is answerable from the warehouse
    contents alone -- a table full of data cannot say when it arrived, or whether
    the run that produced it also failed three quality gates.
    """
    finished = datetime.now(timezone.utc)
    con.cursor().execute(
        "INSERT INTO tr_gov.etl_run (engine, started_at, finished_at, duration_ms, "
        "rows_loaded, dq_passed, dq_failed, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (engine, started, finished,
         int((finished - started).total_seconds() * 1000),
         n_rows, passed, failed, "SUCCESS" if failed == 0 else "FAILED"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["duckdb", "postgres"], default="duckdb")
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "warehouse.duckdb"))
    ap.add_argument("--dsn", default=os.environ.get("TRANSFEROPS_DSN", ""))
    args = ap.parse_args()

    started = datetime.now(timezone.utc)

    if args.engine == "duckdb":
        con = run_duckdb(args.db)
        fetch = lambda q: con.execute(q).fetchall()
    else:
        con = run_postgres(args.dsn)
        cur = con.cursor()
        def fetch(q):
            cur.execute(q); return cur.fetchall()

    n = fetch("SELECT COUNT(*) FROM tr_core.dim_project")[0][0]
    print(f"Loaded warehouse ({args.engine}): {n} projects in tr_core.dim_project.\n")

    print("Data-quality gates:")
    ok = True
    passed = failed = 0
    for name, gate_ok, detail in data_quality(fetch):
        print(f"  [{'PASS' if gate_ok else 'FAIL'}] {name}  ({detail})")
        ok = ok and gate_ok
        passed += gate_ok
        failed += (not gate_ok)
    print()

    if args.engine == "postgres":
        record_run(con, args.engine, started, n, passed, failed)

    return con, fetch, ok


if __name__ == "__main__":
    main()
