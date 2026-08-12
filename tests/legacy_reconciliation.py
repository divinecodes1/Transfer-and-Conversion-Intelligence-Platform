"""
Transfer & Conversion Intelligence Platform :: legacy vs governed reconciliation.

This is the migration rule made executable, and the demo moment the architecture
doc calls out: **the business number is the same; everything else is different.**

Two things get proved here, and they pull in opposite directions on purpose:

  1. `legacy/v0_legacy.sql` reproduces the governed numbers exactly, across the
     whole portfolio. Without this, "we modernised the platform" is indistinguishable
     from "we changed the numbers and hoped nobody checked" -- which is the single
     fastest way to lose a business owner's trust during a migration.

  2. The legacy layer nonetheless already contradicts itself. Two views in that
     one file answer the same question with different rules, and the suite
     quantifies the disagreement. That is what the governed layer removes.

So the argument is not "the old SQL was wrong". It is "the old SQL was right, and
still could not tell you which answer the business meant."
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
from run import run_duckdb, split_statements  # noqa: E402

LEGACY_SQL = os.path.join(os.path.dirname(__file__), "..", "legacy", "v0_legacy.sql")
FIELDS = ("actual_cycle_time_days", "schedule_deviation_days",
          "completion_variance_days", "on_time")


def run():
    db = os.path.join(os.path.dirname(__file__), "..", "warehouse_legacy.duckdb")
    con = run_duckdb(db)
    with open(LEGACY_SQL, encoding="utf-8") as f:
        for stmt in split_statements(f.read()):
            con.execute(stmt)
    fetch = lambda q: con.execute(q).fetchall()

    passed = failed = 0

    def check(name, ok, detail):
        nonlocal passed, failed
        passed += ok
        failed += (not ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")

    print("Legacy (v0) vs governed (v1) reconciliation")
    print("=" * 74)

    # ---- 1. the numbers agree -------------------------------------------
    print("\nthe business number is the same")
    for field in FIELDS:
        mismatches = fetch(f"""
            SELECT COUNT(*) FROM legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2 v0
            FULL OUTER JOIN tr_metric.v_project_kpi v1 USING (project_id)
            WHERE v0.{field} IS DISTINCT FROM v1.{field}
        """)[0][0]
        covered = fetch(f"""
            SELECT COUNT(*) FROM legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2
            WHERE {field} IS NOT NULL
        """)[0][0]
        check(f"{field} reconciles across the portfolio", mismatches == 0,
              f"{covered} projects in population, {mismatches} disagreements")

    both = fetch("""
        SELECT COUNT(*) FROM legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2 v0
        JOIN tr_metric.v_project_kpi v1 USING (project_id)
    """)[0][0]
    check("every project is present in both layers", both == 260,
          f"{both} projects matched by project_id")

    # ---- 2. the legacy layer already disagrees with itself ---------------
    print("\nand yet the legacy layer contradicts itself")

    drift, flattered = fetch("""
        SELECT COUNT(*),
               SUM(CASE WHEN b.on_time AND NOT a.on_time THEN 1 ELSE 0 END)
        FROM legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2 a
        JOIN legacy.VIEW_DASHBOARD_HEALTH_FIX b USING (project_id)
        WHERE a.on_time IS DISTINCT FROM b.on_time
    """)[0]
    rate_baseline, rate_latest = fetch("""
        SELECT ROUND(AVG(CASE WHEN a.on_time THEN 100.0 ELSE 0 END), 1),
               ROUND(AVG(CASE WHEN b.on_time THEN 100.0 ELSE 0 END), 1)
        FROM legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2 a
        JOIN legacy.VIEW_DASHBOARD_HEALTH_FIX b USING (project_id)
        WHERE a.on_time IS NOT NULL
    """)[0]
    check("two legacy views give different on-time answers", drift > 0,
          f"{drift} projects disagree ({flattered} of them look on-time only in the "
          f"second view). On-time rate reads {rate_baseline}% against the frozen "
          f"baseline vs {rate_latest}% against the latest replan — the same "
          f"portfolio, scored against goalposts that moved with it.")

    legacy_health = {r[0]: r[1] for r in fetch("""
        SELECT health, COUNT(*) FROM legacy.VIEW_DASHBOARD_HEALTH_FIX
        WHERE status IN ('ACTIVE','PLANNED') GROUP BY health
    """)}
    governed_health = {r[0]: r[1] for r in fetch("""
        SELECT health, COUNT(*) FROM tr_mart.mart_project_status GROUP BY health
    """)}
    check("legacy health bands disagree with the governed mart",
          legacy_health != governed_health,
          f"legacy {dict(sorted(legacy_health.items()))} vs "
          f"governed {dict(sorted(governed_health.items()))}")

    # ---- 3. what the governed layer has that the legacy layer cannot -----
    print("\nwhat v1 has that v0 structurally cannot")

    text = open(LEGACY_SQL, encoding="utf-8").read().lower()
    inline = text.count("planned_finish - ") + text.count("actual_finish - ")
    check("legacy duplicates its KPI formulas inline", inline >= 4,
          f"{inline} inline date-arithmetic KPI expressions, "
          f"vs 1 governed definition each in tr_metric")

    registered, complete = fetch("""
        SELECT
            COUNT(*),
            SUM(CASE
                WHEN COALESCE(TRIM(owner), '') <> ''
                 AND COALESCE(TRIM(population), '') <> ''
                 AND COALESCE(TRIM(version), '') <> ''
                THEN 1 ELSE 0
            END)
        FROM tr_gov.metric_definition
    """)[0]
    check("governed metrics are registered with owner, population and version",
          registered >= 9 and complete == registered,
          f"{complete} of {registered} metrics have complete governance metadata; legacy has 0")

    # The legacy report keeps only current-state schedule columns, so a question
    # about what was believed three months ago has nowhere to go.
    snapshots = fetch("SELECT COUNT(*) FROM tr_core.fact_project_snapshot")[0][0]
    horizons = fetch("""
        SELECT COUNT(DISTINCT CASE WHEN horizon_days >= 90 THEN '90+'
                                   WHEN horizon_days >= 30 THEN '30-89'
                                   ELSE '0-29' END)
        FROM tr_metric.v_forecast_error WHERE horizon_days >= 0
    """)[0][0]
    check("forecast accuracy by horizon exists only in the governed layer",
          horizons >= 3,
          f"{snapshots:,} preserved snapshots give {horizons} horizon bands; "
          f"the legacy report has no forecast history at all")

    print("\n" + "=" * 74)
    print("  Same numbers. One of them is governed, tested, versioned and")
    print("  answerable about the past.")
    print(f"\n  {passed} passed, {failed} failed")
    con.close()
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
