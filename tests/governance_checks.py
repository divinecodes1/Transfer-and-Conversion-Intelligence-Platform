"""
Transfer & Conversion Intelligence Platform :: metric-governance reconciliation.

The project's central claim is that every KPI has exactly one governed definition,
registered in tr_gov.metric_definition and implemented once in the calculation
layer. That claim is only worth anything if something enforces it -- otherwise the
catalogue drifts from the code and the AI agent (which resolves user questions BY
querying the catalogue) starts promising metrics that do not exist, or returning a
population the definition says is excluded.

Three gates:
  1. registration   -- every registered metric has an implementation, and every
                       implementation is registered. No orphans in either direction.
  2. resolution     -- the named object/column actually resolves in the warehouse.
  3. population     -- a metric whose definition excludes cancelled projects
                       contains no cancelled projects.

Gate 3 is what caught BASELINE_FINISH_DEVIATION_DAYS returning all 9 cancelled
projects while its registered exclusions said "Cancelled projects".
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
from run import run_duckdb  # noqa: E402

# metric_code -> (object, value column). The single place the catalogue is bound
# to the code that implements it; adding a metric to the dictionary without adding
# it here fails gate 1 rather than silently shipping an unimplemented metric.
IMPLEMENTS = {
    "ACTUAL_TRANSFER_CYCLE_TIME":     ("tr_metric.v_project_cycle_time",       "actual_cycle_time_days"),
    "FORECAST_CYCLE_TIME":            ("tr_metric.v_forecast_cycle_time",      "forecast_cycle_time_days"),
    "BASELINE_FINISH_DEVIATION_DAYS": ("tr_metric.v_schedule_deviation",       "schedule_deviation_days"),
    "COMPLETION_VARIANCE_DAYS":       ("tr_metric.v_completion_variance",      "completion_variance_days"),
    "FORECAST_ERROR_DAYS":            ("tr_metric.v_forecast_error",           "forecast_error_days"),
    "STAGE_CYCLE_TIME":               ("tr_metric.v_stage_cycle_time",         "stage_cycle_time_days"),
    "TRANSFER_THROUGHPUT":            ("tr_mart.mart_portfolio_period",        "throughput"),
    "ON_TIME_COMPLETION_RATE":        ("tr_mart.mart_portfolio_period",        "on_time_rate"),
    "CYCLE_TIME_DISTRIBUTION":        ("tr_mart.mart_cycle_time_distribution", "p50_median"),
    "REPLAN_RATE":                    ("tr_metric.v_project_replan",           "was_replanned"),
    "WIP_AGE_DAYS":                   ("tr_metric.v_project_wip",              "wip_age_days"),
    # PORTFOLIO_WIP is a count, so its "value column" is the grain itself: the
    # metric is the population of this view, and binding it to the key is what
    # makes gate 3 able to prove no cancelled project is being counted as WIP.
    "PORTFOLIO_WIP":                  ("tr_metric.v_project_wip",              "project_key"),
}


def run():
    db = os.path.join(os.path.dirname(__file__), "..", "warehouse_gov.duckdb")
    con = run_duckdb(db)
    fetch = lambda q: con.execute(q).fetchall()

    results = []  # (name, passed, detail)

    # ---- Gate 1: registration -------------------------------------------------
    registered = {r[0]: r[1] for r in fetch(
        "SELECT metric_code, exclusions FROM tr_gov.metric_definition")}

    unimplemented = sorted(set(registered) - set(IMPLEMENTS))
    results.append(("every registered metric is implemented",
                    not unimplemented,
                    f"unimplemented: {unimplemented}" if unimplemented
                    else f"all {len(registered)} registered metrics implemented"))

    unregistered = sorted(set(IMPLEMENTS) - set(registered))
    results.append(("every implemented metric is registered",
                    not unregistered,
                    f"unregistered: {unregistered}" if unregistered
                    else "no metric bypasses the catalogue"))

    # ---- Gate 2: resolution ---------------------------------------------------
    unresolved = []
    for code, (obj, col) in sorted(IMPLEMENTS.items()):
        try:
            fetch(f"SELECT {col} FROM {obj} LIMIT 0")
        except Exception as exc:
            unresolved.append(f"{code} -> {obj}.{col} ({type(exc).__name__})")
    results.append(("every metric resolves to a real object.column",
                    not unresolved,
                    "; ".join(unresolved) if unresolved
                    else f"{len(IMPLEMENTS)} bindings resolve"))

    # ---- Gate 3: population ---------------------------------------------------
    # Only objects carrying project_key can be traced back to a status.
    leaks = []
    for code, (obj, _col) in sorted(IMPLEMENTS.items()):
        if "cancel" not in (registered.get(code) or "").lower():
            continue
        try:
            fetch(f"SELECT project_key FROM {obj} LIMIT 0")
        except Exception:
            continue  # aggregate mart, no project grain to check
        n = fetch(f"SELECT COUNT(*) FROM {obj} m "
                  f"JOIN tr_core.dim_project p USING (project_key) "
                  f"WHERE p.status = 'CANCELLED'")[0][0]
        if n:
            leaks.append(f"{code} contains {n} cancelled")
    results.append(("metrics excluding cancelled contain no cancelled projects",
                    not leaks,
                    "; ".join(leaks) if leaks else "no population leaks"))

    print("Metric-governance reconciliation")
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
