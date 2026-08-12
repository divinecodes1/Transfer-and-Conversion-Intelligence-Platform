"""
Transfer & Conversion Intelligence Platform :: the scheduled AI refresh.

Runs nightly, after the warehouse load. It warms the narrative cache for the
scopes people actually open and re-scores in-flight projects against the new
vintage, so the first person at their desk gets a briefing about *this* load
rather than waiting on a model.

Ordering is the point: this runs **after** the ETL, never before and never
concurrently. A narrative generated against a half-loaded warehouse is not a
stale narrative, it is a wrong one, and it would carry the new vintage stamp
while describing the old data. `dags/transferops_pipeline.py` sequences it behind
the quality gates for exactly that reason.

Design decisions worth stating:

  * **Failure is per scope, not per run.** One scope that fails leaves the others
    refreshed and lands in the run log with its error. A nightly job that
    abandons nine good briefings over the tenth is a job that quietly stops
    producing anything.

  * **The run log is written even when the run fails.** A refresh that never
    happened and a refresh that failed look identical from the dashboard unless
    the failure is recorded — and "nobody noticed for a fortnight" is the normal
    outcome for an unmonitored scheduled job.

  * **Scopes are portfolios, not the cross-product of every filter.** Warming
    every combination of five filters is thousands of model calls for scopes
    nobody opens. The portfolio rollups plus the unfiltered whole are what the
    overview and reports screens actually request.
"""
import os
import time

from . import gateway, insights, risk, snapshot as snap, store
from .errors import AiError

# The narrative kinds worth having ready before anyone asks. `anomaly_watch` is
# deliberately not pre-generated for every scope -- it is cheap to produce on
# demand and its value is in being current, not in being instant.
WARM_KINDS = ("portfolio_overview", "report_summary")

RISK_LIMIT = int(os.environ.get("TRANSFEROPS_AI_RISK_LIMIT", "60"))


def scopes(api):
    """
    The filter scopes to warm: the whole portfolio, then one per portfolio.

    Read from the governed filter options rather than hard-coded, so a new
    portfolio starts getting a nightly briefing without a code change -- and an
    entitlement-scoped caller warms only what it can see.
    """
    out = [{}]
    try:
        options = api.get("/mart/filter-options").get("options") or {}
    except Exception:  # noqa: BLE001 -- an unreachable API is the caller's problem
        return out
    for portfolio in options.get("portfolio") or []:
        out.append({"portfolio": portfolio})
    return out


def refresh_insights(api, trigger="cron"):
    """Warm the narrative cache for every scope. Returns the run summary."""
    run_id = store.start_run("insight_refresh", trigger,
                             gateway.model_name(), gateway.provider_name())
    started = time.perf_counter()
    warmed, errors, touched = 0, [], []

    try:
        for scope in scopes(api):
            label = snap.describe_scope(scope)
            for kind in WARM_KINDS:
                try:
                    store.save_insight(insights.generate(api, kind, scope))
                    warmed += 1
                    touched.append(f"{kind}:{label}")
                except AiError as exc:
                    errors.append(f"{kind} [{label}]: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{kind} [{label}]: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 -- record, then re-raise
        store.finish_run(run_id, "failed", item_count=warmed, scopes=touched,
                         error_message=f"{type(exc).__name__}: {exc}")
        raise

    status = "success" if not errors else ("failed" if warmed == 0 else "success")
    store.finish_run(
        run_id, status, item_count=warmed, scopes=touched,
        detail=f"{warmed} narrative(s) across {len(scopes(api))} scope(s)",
        error_message="; ".join(errors[:5]) or None)
    return {"job": "insight_refresh", "status": status, "warmed": warmed,
            "scopes": touched, "errors": errors,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


def refresh_risk(api, trigger="cron", limit=RISK_LIMIT):
    """Re-score in-flight projects against the current vintage."""
    run_id = store.start_run("risk_refresh", trigger,
                             gateway.model_name(), gateway.provider_name())
    started = time.perf_counter()

    try:
        vintage = (api.get("/mart/kpis") or {}).get("data_as_of")
        result = risk.score(api, limit=limit)
        stored = store.save_risk(result["scored"], data_as_of=vintage)
    except Exception as exc:  # noqa: BLE001 -- record, then re-raise
        store.finish_run(run_id, "failed",
                         error_message=f"{type(exc).__name__}: {exc}")
        raise

    errors = result.get("failures") or []
    status = "success" if stored else "failed"
    store.finish_run(
        run_id, status, item_count=stored,
        detail=f"{stored} of {result['considered']} in-flight project(s) scored",
        error_message="; ".join(errors[:5]) or None)
    return {"job": "risk_refresh", "status": status, "scored": stored,
            "considered": result["considered"], "errors": errors,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


def run_all(api, trigger="cron"):
    """
    Both jobs, in order, each recorded separately.

    Separate run rows rather than one combined row: "the AI refresh failed" is
    not actionable, and the two jobs fail for different reasons -- narratives on
    a prompt or context problem, scoring on a schema or batch problem.
    """
    if not gateway.configured():
        return {"status": "skipped",
                "detail": "No model configured; nothing to refresh."}
    return {"status": "ok",
            "jobs": [refresh_insights(api, trigger), refresh_risk(api, trigger)]}


def main():
    """CLI entry point: `python -m ai.refresh`, and what the DAG task calls."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Refresh the Transfer & Conversion Intelligence Platform AI caches.")
    parser.add_argument("--api", default=os.environ.get(
        "TRANSFEROPS_API", "http://127.0.0.1:8000"))
    parser.add_argument("--identity", default=os.environ.get(
        "TRANSFEROPS_AI_IDENTITY", "admin"),
        help="the identity the refresh runs as; its entitlements bound every "
             "scope it can warm")
    parser.add_argument("--job", choices=["all", "insights", "risk"], default="all")
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    from bi.client import Api
    api = Api(base_url=args.api, identity=args.identity)

    if args.job == "insights":
        result = refresh_insights(api, args.trigger)
    elif args.job == "risk":
        result = refresh_risk(api, args.trigger)
    else:
        result = run_all(api, args.trigger)

    print(result)
    failed = result.get("status") == "failed" or any(
        job.get("status") == "failed" for job in result.get("jobs", []))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
