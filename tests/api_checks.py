"""
Transfer & Conversion Intelligence Platform :: API contract checks.

Beyond "does it return 200", these assert the three properties the API exists to
guarantee, because each one is a promise the agent layer will later depend on:

  * every metric answer is self-describing -- definition, population, filters and
    data vintage travel with the numbers;
  * the service physically cannot write to the warehouse;
  * the numbers the API serves are the same numbers the golden reconciliation
    asserts, so the API cannot drift from the metric layer.

Requires the PostgreSQL warehouse to be loaded:
    docker compose up -d
    python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# These suites drive the demo identities (manager.auto, admin.demo) instead of
# standing up Keycloak, so they opt into demo mode explicitly. The platform
# default is enforce -- security is never opt-in -- and tests/security_checks.py
# asserts that default plus the fact that X-Demo-User is refused without it.
os.environ.setdefault("TRANSFEROPS_AUTH", "demo")

from fastapi.testclient import TestClient  # noqa: E402

from api import db  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def envelope_is_complete(payload):
    """A metric response must never arrive without its own provenance."""
    if not payload.get("metrics"):
        return False, "no metric definitions attached"
    for m in payload["metrics"]:
        missing = [f for f in ("metric_code", "definition", "population", "version")
                   if not m.get(f)]
        if missing:
            return False, f"{m.get('metric_code')} missing {missing}"
    if "data_as_of" not in payload:
        return False, "no data_as_of"
    if "filters_applied" not in payload:
        return False, "no filters_applied"
    return True, "definition + population + version + vintage present"


# ---------------------------------------------------------------------------
@check("service reports healthy and reaches the warehouse")
def _():
    r = client.get("/health")
    body = r.json()
    return (r.status_code == 200 and body["status"] == "healthy"
            and body["projects"] == 260), f"{r.status_code}, {body.get('projects')} projects"


@check("catalogue serves every registered metric")
def _():
    r = client.get("/catalogue")
    codes = [m["metric_code"] for m in r.json()["metrics"]]
    registered = db.fetch_one(
        "SELECT COUNT(*) AS n FROM tr_gov.metric_definition", scope="*")["n"]
    complete = len(codes) == registered and len(set(codes)) == registered
    return complete, (
        f"API returned {len(codes)} unique metrics; catalogue contains {registered}"
    )


@check("every metric endpoint returns a complete provenance envelope")
def _():
    endpoints = ["/metrics/cycle-time", "/metrics/schedule-drift",
                 "/metrics/forecast", "/metrics/stage-cycle-time",
                 "/metrics/portfolio"]
    for ep in endpoints:
        r = client.get(ep)
        if r.status_code != 200:
            return False, f"{ep} -> {r.status_code}"
        ok, detail = envelope_is_complete(r.json())
        if not ok:
            return False, f"{ep}: {detail}"
    return True, f"{len(endpoints)} endpoints self-describing"


@check("forecast error grows with horizon (the late-revision effect)")
def _():
    series = client.get("/metrics/forecast").json()["series"]
    by_bucket = {r["horizon_bucket"]: r["median_abs_error"] for r in series}
    order = ["0-29", "30-59", "60-89", "90+"]
    vals = [by_bucket[b] for b in order if b in by_bucket]
    rising = all(a <= b for a, b in zip(vals, vals[1:]))
    return rising, " < ".join(f"{b}:{by_bucket[b]:.0f}d" for b in order if b in by_bucket)


@check("cycle-time grouping is filterable and whitelisted")
def _():
    r = client.get("/metrics/cycle-time", params={"group_by": "transfer_type"})
    n_groups = len(r.json()["series"])
    bad = client.get("/metrics/cycle-time", params={"group_by": "; DROP TABLE"})
    return (r.status_code == 200 and n_groups > 1 and bad.status_code == 400,
            f"{n_groups} transfer types; unknown group_by rejected with {bad.status_code}")


@check("API cycle time matches the golden reconciliation for T-017")
def _():
    r = client.get("/projects/T-017")
    p = r.json()["project"]
    expected = {"actual_cycle_time_days": 118, "schedule_deviation_days": 25,
                "completion_variance_days": 28}
    wrong = {k: (p[k], v) for k, v in expected.items() if p[k] != v}
    baseline = [rev for rev in r.json()["schedule_revisions"] if rev["is_baseline"]]
    return (not wrong and len(baseline) == 1,
            f"118/25/28 reproduced, {len(r.json()['schedule_revisions'])} revisions, "
            f"{len(baseline)} immutable baseline")


@check("project filters narrow the portfolio")
def _():
    everything = client.get("/projects").json()["total_matching"]
    late = client.get("/projects", params={"health": "LATE"}).json()["total_matching"]
    return (0 < late < everything,
            f"{late} LATE of {everything} open projects")


@check("unknown project returns 404, not an empty success")
def _():
    r = client.get("/projects/NOPE-999")
    return r.status_code == 404, f"status {r.status_code}"


@check("the API's database session physically cannot write")
def _():
    try:
        db.fetch("CREATE TABLE tr_metric.should_not_exist (x INT)")
        return False, "a write succeeded -- the session is not read-only"
    except Exception as exc:
        return "read-only" in str(exc).lower(), type(exc).__name__ + ": " + str(exc).strip()[:60]


def run():
    print("API contract checks")
    print("-" * 72)
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:            # a raising check is a failing check
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
