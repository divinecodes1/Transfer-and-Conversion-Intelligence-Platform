"""
Transfer & Conversion Intelligence Platform :: golden-project reconciliation.

The migration rule from the architecture spec is: never retire a legacy metric
until the new implementation reproduces hand-agreed numbers on a small set of
representative projects. This is the automated version of that gate.

**Why this is not circular.** The expected values are computed here in plain
Python, straight from the CSVs the warehouse was loaded from — never by querying
the views under test. Two independent implementations of the same business rule
have to agree, so a mistake in the SQL cannot quietly define its own correctness.
That is the whole point of a reconciliation gate; a test that asks the system
what it thinks and then asserts it said that would pass forever.

T-017 stays hard-coded from the architecture document itself: one case whose
numbers were agreed by a human before any code existed.

Coverage follows the spec's catalogue — normal, late, early, cancelled,
multi-revision, missing forecast, long-running, cross-fiscal-year, outlier,
open/in-progress. Cancelled projects assert *absence*: they must appear in no
metric view at all, which is the regression test for a population defect that
previously shipped.
"""
import csv, os, sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
from run import run_duckdb  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "data")

# The one case agreed by hand, from the architecture document.
SPEC_CASE = {
    "project_id": "T-017", "actual_cycle_time_days": 118,
    "schedule_deviation_days": 25, "completion_variance_days": 28, "on_time": False,
}

PER_CATEGORY = 3          # keeps the suite in the spec's 20-50 range


def load(name):
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def date(s):
    return dt.date.fromisoformat(s) if s else None


def fiscal_year(d):
    """Infineon fiscal year starts 1 October."""
    return None if d is None else (d.year + 1 if d.month >= 10 else d.year)


def independent_expectations():
    """Recompute every metric from source, without touching the metric layer."""
    projects = {p["project_key"]: p for p in load("dim_project.csv")}

    baseline, latest, n_revs = {}, {}, {}
    for r in load("fact_schedule_revision.csv"):
        pk = r["project_key"]
        n_revs[pk] = n_revs.get(pk, 0) + 1
        if r["is_baseline"] == "True":
            baseline[pk] = date(r["planned_finish"])
        key = (r["revision_timestamp"], int(r["revision_id"]))
        if pk not in latest or key > latest[pk][0]:
            latest[pk] = (key, date(r["planned_finish"]))

    has_snapshot = {s["project_key"] for s in load("fact_project_snapshot.csv")}

    out = {}
    for pk, p in projects.items():
        start, finish = date(p["actual_start"]), date(p["actual_finish"])
        base_fin = baseline.get(pk)
        late_fin = latest[pk][1] if pk in latest else None
        completed = p["status"] == "COMPLETED"
        cancelled = p["status"] == "CANCELLED"

        out[p["project_id"]] = {
            "status": p["status"],
            "cancelled": cancelled,
            "portfolio": p["portfolio"],
            "n_revisions": n_revs.get(pk, 0),
            "has_forecast": pk in has_snapshot,
            # Metrics. None means "this project is outside the metric's population".
            "actual_cycle_time_days":
                (finish - start).days if completed and start and finish else None,
            "schedule_deviation_days":
                (late_fin - base_fin).days
                if not cancelled and base_fin and late_fin else None,
            "completion_variance_days":
                (finish - base_fin).days if completed and finish and base_fin else None,
            "on_time":
                (finish <= base_fin) if completed and finish and base_fin else None,
            "crosses_fy": (fiscal_year(start) != fiscal_year(finish))
                          if start and finish else False,
        }
    return out


def categorise(exp):
    """Pick representative projects per category from the spec's catalogue."""
    completed = {k: v for k, v in exp.items() if v["status"] == "COMPLETED"}
    cycles = sorted((v["actual_cycle_time_days"], k) for k, v in completed.items()
                    if v["actual_cycle_time_days"] is not None)
    p90_cut = cycles[int(len(cycles) * 0.9)][0] if cycles else 0

    def take(pred, pool=None):
        return sorted(k for k, v in (pool or exp).items() if pred(v))[:PER_CATEGORY]

    cats = {
        "on-time":            take(lambda v: v["on_time"] is True, completed),
        "late":               take(lambda v: v["on_time"] is False
                                   and (v["completion_variance_days"] or 0) > 30, completed),
        "early":              take(lambda v: (v["completion_variance_days"] or 0) < -20, completed),
        "cancelled":          take(lambda v: v["cancelled"]),
        "multi-revision":     take(lambda v: v["n_revisions"] >= 5, completed),
        "missing-forecast":   take(lambda v: not v["has_forecast"] and not v["cancelled"]),
        "long-running":       take(lambda v: (v["actual_cycle_time_days"] or 0) >= p90_cut,
                                   completed),
        "cross-fiscal-year":  take(lambda v: v["crosses_fy"], completed),
        "open/in-progress":   take(lambda v: v["status"] == "ACTIVE"),
        "planned":            take(lambda v: v["status"] == "PLANNED"),
    }
    if cycles:
        cats["outlier"] = [cycles[-1][1]]
    return cats


FIELDS = ("actual_cycle_time_days", "schedule_deviation_days",
          "completion_variance_days", "on_time")


def run():
    exp = independent_expectations()
    cats = categorise(exp)

    db = os.path.join(os.path.dirname(__file__), "..", "warehouse_test.duckdb")
    con = run_duckdb(db)
    fetch = lambda q: con.execute(q).fetchall()

    actual = {}
    for row in fetch("SELECT project_id, actual_cycle_time_days, schedule_deviation_days, "
                     "completion_variance_days, on_time FROM tr_metric.v_project_kpi"):
        actual[row[0]] = dict(zip(FIELDS, row[1:]))

    passed = failed = 0
    print("Golden-project reconciliation")
    print("=" * 74)

    # ---- the hand-agreed case -------------------------------------------
    print("\nhand-agreed (architecture document)")
    got = actual.get(SPEC_CASE["project_id"], {})
    for field in FIELDS:
        want = SPEC_CASE[field]
        ok = got.get(field) == want
        passed += ok; failed += (not ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] T-017 {field:26} "
              f"expected={want!s:6} actual={got.get(field)!s:6}")

    # ---- category coverage, independently recomputed ---------------------
    for cat, ids in cats.items():
        if not ids:
            print(f"\n{cat}\n  [WARN] no project in the portfolio matches this category")
            continue
        print(f"\n{cat}  ({len(ids)} projects)")
        for pid in ids:
            want, got = exp[pid], actual.get(pid, {})
            if want["cancelled"]:
                # Cancelled projects are excluded from every metric population.
                leaked = [f for f in FIELDS if got.get(f) is not None]
                ok = not leaked
                passed += ok; failed += (not ok)
                print(f"  [{'PASS' if ok else 'FAIL'}] {pid} excluded from all metrics"
                      + (f" — leaked {leaked}" if leaked else ""))
                continue
            diffs = [f"{f}: want {want[f]}, got {got.get(f)}"
                     for f in FIELDS if want[f] != got.get(f)]
            ok = not diffs
            passed += ok; failed += (not ok)
            summary = ", ".join(f"{f.replace('_days','').replace('actual_','')}="
                                f"{want[f]}" for f in FIELDS if want[f] is not None)
            print(f"  [{'PASS' if ok else 'FAIL'}] {pid} {summary or '(no metrics in population)'}")
            for dline in diffs:
                print(f"         {dline}")

    # ---- portfolio-wide invariants ---------------------------------------
    print("\nportfolio invariants")
    for name, sql, want in [
        ("cycle time never negative",
         "SELECT COUNT(*) FROM tr_metric.v_project_cycle_time "
         "WHERE actual_cycle_time_days < 0", 0),
        ("completion variance only for completed",
         "SELECT COUNT(*) FROM tr_metric.v_completion_variance cv "
         "JOIN tr_core.dim_project p USING (project_key) "
         "WHERE p.status <> 'COMPLETED'", 0),
        ("forecast error requires an actual outcome",
         "SELECT COUNT(*) FROM tr_metric.v_forecast_error f "
         "JOIN tr_core.dim_project p USING (project_key) "
         "WHERE p.actual_finish IS NULL", 0),
    ]:
        got_n = fetch(sql)[0][0]
        ok = got_n == want
        passed += ok; failed += (not ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} ({got_n})")

    print("\n" + "=" * 74)
    n_cases = sum(len(v) for v in cats.values())
    print(f"  {n_cases} golden projects across {len(cats)} categories")
    print(f"  {passed} passed, {failed} failed")
    con.close()
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
