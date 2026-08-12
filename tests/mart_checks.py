"""
Transfer & Conversion Intelligence Platform :: the console's mart layer agrees with the metric layer.

The React console reads a set of rollups that the hand-built dashboard never
needed. Those rollups aggregate governed columns, and an aggregate is exactly
where a population quietly goes wrong: the rule is right, the column is right,
and the answer is still incorrect because the wrong rows were counted.

This suite is the gate for that. It runs on DuckDB with no server, and every
expectation is computed a second way -- from a different view, or from the core
tables -- rather than by asking the mart what it thinks and asserting it said
that.

It is not hypothetical. Writing `AVG(CASE WHEN on_time THEN 100 ELSE 0 END)`
over the register looks equivalent to an on-time rate and is not: the ELSE
swallows the NULL an in-flight project carries, so every unfinished project
scores as having missed its baseline and the portfolio reads 26% instead of
41.5%. Assertion 3 is that bug, pinned.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
from run import run_duckdb  # noqa: E402

REGISTER = "tr_mart.mart_project_register"


def run():
    db = os.path.join(os.path.dirname(__file__), "..", "warehouse_mart.duckdb")
    con = run_duckdb(db)

    def one(sql):
        return con.execute(sql).fetchone()[0]

    def rows(sql):
        return con.execute(sql).fetchall()

    results = []

    # ---- 1: population -----------------------------------------------------
    cancelled = one(f"""
        SELECT COUNT(*) FROM {REGISTER} r
        JOIN tr_core.dim_project p USING (project_key)
        WHERE p.status = 'CANCELLED'""")
    total = one(f"SELECT COUNT(*) FROM {REGISTER}")
    expected = one("SELECT COUNT(*) FROM tr_core.dim_project WHERE status <> 'CANCELLED'")
    results.append(("the register is every non-cancelled project, exactly once",
                    cancelled == 0 and total == expected,
                    f"{total} rows, {expected} non-cancelled projects, {cancelled} cancelled"))

    # ---- 2: one health band ------------------------------------------------
    # mart_project_status is a population filter over the register, not a second
    # copy of the CASE. If the two ever disagree for a project, the threshold has
    # been written twice.
    disagreements = one(f"""
        SELECT COUNT(*) FROM {REGISTER} r
        JOIN tr_mart.mart_project_status s USING (project_id)
        WHERE r.health <> s.health""")
    results.append(("the health band is defined in exactly one place",
                    disagreements == 0,
                    f"{disagreements} project(s) banded differently by the two marts"))

    # ---- 3: the population guard on rates ---------------------------------
    # Recomputed from the completion-variance view, which only ever contains
    # completed projects with a baseline -- the population the metric is defined
    # for. The register additionally holds in-flight projects, whose on_time is
    # NULL, and they must not be counted as misses.
    mart_rate = one(f"""
        SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE on_time)
                   / NULLIF(COUNT(*) FILTER (WHERE on_time IS NOT NULL), 0), 4)
        FROM {REGISTER}""")
    independent = one("""
        SELECT ROUND(100.0 * AVG(CASE WHEN on_time THEN 1.0 ELSE 0.0 END), 4)
        FROM tr_metric.v_completion_variance""")
    naive = one(f"SELECT ROUND(AVG(CASE WHEN on_time THEN 100.0 ELSE 0.0 END), 4) FROM {REGISTER}")
    results.append(("the on-time rate counts only projects that could be on time",
                    mart_rate == independent,
                    f"mart {mart_rate}% = metric layer {independent}% "
                    f"(the NULL-swallowing form would report {naive}%)"))

    # ---- 4: a rate that is always the same is a broken rate ---------------
    replan_rate = one(f"""
        SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE was_replanned)
                   / NULLIF(COUNT(*) FILTER (WHERE was_replanned IS NOT NULL), 0), 1)
        FROM {REGISTER}""")
    results.append(("the replan rate discriminates between projects",
                    replan_rate is not None and 0 < replan_rate < 100,
                    f"{replan_rate}% of projects carry more than one revision"))

    # ---- 5: WIP age population --------------------------------------------
    finished_with_age = one(f"""
        SELECT COUNT(*) FROM {REGISTER}
        WHERE wip_age_days IS NOT NULL AND actual_finish IS NOT NULL""")
    started_without_age = one(f"""
        SELECT COUNT(*) FROM {REGISTER}
        WHERE wip_age_days IS NULL AND actual_start IS NOT NULL AND actual_finish IS NULL""")
    results.append(("WIP age covers in-flight projects and only those",
                    finished_with_age == 0 and started_without_age == 0,
                    f"{finished_with_age} finished project(s) carry a WIP age, "
                    f"{started_without_age} in-flight project(s) are missing one"))

    # ---- 6: WIP age is measured against the vintage, not the clock --------
    vintage = one("SELECT data_as_of FROM tr_metric.v_data_vintage")
    snapshot_max = one("SELECT MAX(snapshot_date) FROM tr_core.fact_project_snapshot")
    drift = one("""
        SELECT COUNT(*) FROM tr_metric.v_project_wip
        WHERE wip_age_days <> (SELECT data_as_of FROM tr_metric.v_data_vintage) - actual_start""")
    results.append(("WIP age is reproducible against the data vintage",
                    vintage == snapshot_max and drift == 0,
                    f"measured from {vintage}, not from the wall clock, "
                    f"so a printed figure recomputes tomorrow"))

    # ---- 7: filter options are derived ------------------------------------
    dimensions = {row[0] for row in rows("SELECT DISTINCT dimension FROM tr_mart.mart_filter_options")}
    expected_dimensions = {"fiscal_year", "transfer_type", "portfolio", "complexity_class",
                           "source_site", "target_site", "status", "health"}
    stray = one("""
        SELECT COUNT(*) FROM tr_mart.mart_filter_options o
        WHERE o.dimension = 'portfolio'
          AND o.value NOT IN (SELECT DISTINCT portfolio FROM tr_core.dim_project
                              WHERE portfolio IS NOT NULL)""")
    results.append(("the filter vocabulary is derived from the data",
                    dimensions == expected_dimensions and stray == 0,
                    f"{len(dimensions)} dimensions, no value that is not in the warehouse"))

    # ---- 8: horizon buckets are ordered and consistent --------------------
    ordering = rows("""
        SELECT horizon_bucket, MIN(horizon_days), MAX(horizon_days), MIN(horizon_floor)
        FROM tr_metric.v_forecast_error_horizon GROUP BY horizon_bucket
        ORDER BY MIN(horizon_floor)""")
    contiguous = all(row[1] >= row[3] for row in ordering)
    mislabelled = one("""
        SELECT COUNT(*) FROM tr_metric.v_forecast_error_horizon
        WHERE within_14_days <> (abs_forecast_error_days <= 14)""")
    results.append(("forecast horizon buckets and the hit threshold agree with the data",
                    contiguous and mislabelled == 0,
                    f"{len(ordering)} buckets in order; "
                    f"{mislabelled} row(s) flagged inconsistently with their own error"))

    # ---- 9: the register carries what the console needs -------------------
    columns = {row[0] for row in rows(f"DESCRIBE {REGISTER}")}
    required = {"project_key", "project_id", "project_name", "health", "revision_count",
                "was_replanned", "wip_age_days", "schedule_deviation_days",
                "completion_variance_days", "on_time", "baseline_finish",
                "latest_forecast_finish", "completion_fiscal_year"}
    missing = sorted(required - columns)
    results.append(("the register exposes every column the console reads",
                    not missing,
                    f"missing: {missing}" if missing else f"{len(required)} required columns present"))

    print("Mart layer checks")
    print("-" * 72)
    passed = failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    con.close()
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
