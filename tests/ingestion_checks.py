"""
Transfer & Conversion Intelligence Platform :: layered ingestion checks.

Four properties, each of which is the reason the RAW/STAGING split earns its keep:

  * a clean batch reaches CORE unchanged;
  * a corrupted batch reaches CORE *equally* unchanged, with the bad rows held
    back and named -- one malformed record from an upstream system costs you that
    record, not the portfolio;
  * RAW still holds exactly what the source sent, so "did they send it wrong or
    did we transform it wrong?" is answerable by looking rather than arguing;
  * re-delivering the same data is a no-op, which is what makes the pipeline safe
    to retry and therefore safe to backfill.

The last check reconciles the layered path against the bulk loader that actually
deploys. Two loaders that disagree would mean the ingestion demo was describing a
pipeline nobody runs.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from etl.ingest import FEEDS, ingest, land  # noqa: E402
from etl.run import run_duckdb  # noqa: E402

SCRATCH = os.path.join(os.path.dirname(__file__), "..")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def db(name):
    return os.path.join(SCRATCH, name)


@check("a clean batch flows through every tier into CORE")
def _():
    con, s = ingest(db("warehouse_ing_clean.duckdb"), verbose=False)
    try:
        return (s["core_projects"] == 260 and not s["ingestion_failures"]
                and not s["core_failures"] and not s["metric_failures"],
                f"{s['landed']:,} rows landed, {s['core_projects']} projects, "
                f"0 findings across all three tiers")
    finally:
        con.close()


@check("a corrupted batch is caught at the ingestion tier, by the right check")
def _():
    con, s = ingest(db("warehouse_ing_bad.duckdb"), corrupt=True, verbose=False)
    try:
        found = {name for name, _sev, _rows in s["ingestion_failures"]}
        expected = {"dates parse", "status is in the approved domain",
                    "mandatory project fields are populated"}
        return expected <= found, f"caught: {sorted(found)}"
    finally:
        con.close()


@check("only REJECT findings hold a row back; WARN findings do not")
def _():
    con, s = ingest(db("warehouse_ing_bad2.duckdb"), corrupt=True, verbose=False)
    try:
        by_sev = {}
        for _n, sev, rows in s["ingestion_failures"]:
            by_sev.setdefault(sev, 0)
            by_sev[sev] += len(rows)
        held = con.execute(
            "SELECT COUNT(DISTINCT source_record_id) FROM tr_raw.quarantine "
            "WHERE severity = 'REJECT'").fetchone()[0]
        # The duplicate key and duplicate payload are WARNs: staging resolves them,
        # so the affected project must still be in CORE.
        dup_present = con.execute(
            "SELECT COUNT(*) FROM tr_core.dim_project WHERE project_key = 4"
        ).fetchone()[0]
        return (held == 3 and dup_present == 1 and by_sev.get("WARN", 0) == 2,
                f"{by_sev}, {held} rows held back, duplicate-key project still "
                f"present ({dup_present})")
    finally:
        con.close()


@check("the corrupted batch still lands the same clean portfolio")
def _():
    clean, cs = ingest(db("warehouse_ing_c2.duckdb"), verbose=False)
    bad, bs = ingest(db("warehouse_ing_b2.duckdb"), corrupt=True, verbose=False)
    try:
        return (cs["core_projects"] == bs["core_projects"] == 260
                and not bs["core_failures"] and not bs["metric_failures"],
                f"clean={cs['core_projects']}, corrupted={bs['core_projects']}, "
                f"CORE and METRIC tiers clean in both")
    finally:
        clean.close(); bad.close()


@check("RAW preserves what the source sent, byte for byte")
def _():
    con, _ = ingest(db("warehouse_ing_raw.duckdb"), corrupt=True, verbose=False)
    try:
        raw = con.execute(
            "SELECT actual_start FROM tr_raw.raw_project WHERE project_key = '9001'"
        ).fetchone()
        staged = con.execute(
            "SELECT COUNT(*) FROM tr_stg.stg_project WHERE project_key = 9001"
        ).fetchone()[0]
        # The malformed date survives in RAW; STAGING is where it stops.
        return (raw and raw[0] == "2026-13-45",
                f"RAW still holds '{raw[0] if raw else None}'; "
                f"staging rows for that project: {staged}")
    finally:
        con.close()


@check("re-delivering the same batch is a no-op")
def _():
    con, _ = ingest(db("warehouse_ing_idem.duckdb"), verbose=False)
    try:
        before = con.execute("SELECT COUNT(*) FROM tr_stg.stg_project").fetchone()[0]
        raw_before = con.execute(
            "SELECT COUNT(*) FROM tr_raw.raw_project").fetchone()[0]
        # Same rows, delivered again under a new batch id -- the normal shape of
        # an upstream retry.
        land(con, "dim_project.csv", *FEEDS["dim_project.csv"], "batch-redelivery")
        raw_after = con.execute(
            "SELECT COUNT(*) FROM tr_raw.raw_project").fetchone()[0]
        after = con.execute("SELECT COUNT(*) FROM tr_stg.stg_project").fetchone()[0]
        return (before == after == 260 and raw_after == raw_before * 2,
                f"RAW doubled {raw_before} -> {raw_after} (history kept), "
                f"STAGING held at {after} (newest wins)")
    finally:
        con.close()


@check("the same layered pipeline runs on PostgreSQL")
def _():
    # The staging SQL is byte-identical across engines; only the safe-cast shim
    # differs. This is the check that stops that claim from rotting.
    dsn = os.environ.get("TRANSFEROPS_DSN",
                         "postgresql://app:dev@localhost:5432/transferops")
    con, s = ingest(engine="postgres", dsn=dsn, corrupt=True, verbose=False)
    try:
        rls = con.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'tr_core.dim_project'::regclass").fetchone()
        return (s["core_projects"] == 260 and not s["core_failures"]
                and not s["metric_failures"] and rls[0] and rls[1],
                f"{s['core_projects']} projects, {s['quarantined']} quarantined, "
                f"row-level security restored (enabled={rls[0]} forced={rls[1]})")
    finally:
        con.close()


@check("the layered path and the bulk loader agree on CORE")
def _():
    layered, _ = ingest(db("warehouse_ing_cmp.duckdb"), verbose=False)
    bulk = run_duckdb(db("warehouse_bulk_cmp.duckdb"))
    try:
        q = ("SELECT COUNT(*), SUM(project_key), COUNT(DISTINCT status), "
             "       MIN(actual_start), MAX(actual_finish) "
             "FROM tr_core.dim_project")
        a, b = layered.execute(q).fetchone(), bulk.execute(q).fetchone()
        rev_a = layered.execute(
            "SELECT COUNT(*) FROM tr_core.fact_schedule_revision").fetchone()[0]
        rev_b = bulk.execute(
            "SELECT COUNT(*) FROM tr_core.fact_schedule_revision").fetchone()[0]
        return a == b and rev_a == rev_b, (
            f"{a[0]} projects / {rev_a:,} revisions, identical fingerprints"
            if a == b else f"layered {a} vs bulk {b}")
    finally:
        layered.close(); bulk.close()


def run():
    print("Layered ingestion checks")
    print("-" * 72)
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
