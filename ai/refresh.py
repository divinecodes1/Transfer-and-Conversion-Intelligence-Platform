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

# Wall-clock budget for the WHOLE run; 0 means no bound.
#
# The job is a burst of calls against whatever quota the provider grants, and a
# throttled night is slow rather than failed -- each call waits, retries, and
# eventually succeeds or gives up. Without a bound the run is stopped by
# something that does not know what it is interrupting: the Lambda timeout,
# which kills the process between `start_run` and `finish_run` and leaves the
# row at 'running' forever. On the automation screen that reads as a hang.
#
# So the job stops itself first, with time in hand to record what it warmed and
# what it did not. Set below the platform's own ceiling -- see the refresh
# function in infrastructure/aws/api.tf.
#
# It is one deadline for the run, not one per job, and it is checked before
# every model call. The first version of this was neither, and a throttled night
# walked straight through it: `refresh_risk` started its own budget after
# `refresh_insights` had spent the first, and the check sat between scopes while
# the waiting happened inside them. The run was killed by the 900s ceiling at
# 900706ms, which is the exact outcome the budget exists to prevent.
BUDGET_SECONDS = float(os.environ.get("TRANSFEROPS_AI_REFRESH_BUDGET", "0"))


def deadline_from_now():
    """The moment this run must stop, or None when unbounded."""
    return time.monotonic() + BUDGET_SECONDS if BUDGET_SECONDS else None


def _spent(deadline):
    return deadline is not None and time.monotonic() >= deadline


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
        # Each option is a {value, label} pair: the filter binds on the stable
        # code, the dropdown shows the catalogue's display name. Passing the pair
        # through whole put a dict where a portfolio code belongs, and it reached
        # the driver as a query parameter -- "can't adapt type 'dict'", once per
        # scope, every scope but the unfiltered one. A plain string is still
        # accepted so a caller with a flat vocabulary is not broken by this.
        code = portfolio.get("value") if isinstance(portfolio, dict) else portfolio
        if code is not None:
            out.append({"portfolio": code})
    return out


def refresh_insights(api, trigger="cron", deadline=None):
    """Warm the narrative cache for every scope. Returns the run summary."""
    run_id = store.start_run("insight_refresh", trigger,
                             gateway.model_name(), gateway.provider_name())
    started = time.perf_counter()
    if deadline is None:
        deadline = deadline_from_now()
    warmed, errors, touched = 0, [], []

    stopped_early = None
    try:
        planned = scopes(api)
        for index, scope in enumerate(planned):
            if _spent(deadline):
                stopped_early = (f"stopped after {index} of {len(planned)} "
                                 f"scope(s): the run budget was spent, most "
                                 f"likely waiting on a throttled provider")
                break
            label = snap.describe_scope(scope)
            for kind in WARM_KINDS:
                # Checked per call, not per scope: the waiting happens inside a
                # scope, so a check only at the boundary can overshoot by a
                # whole scope's worth of retries.
                if _spent(deadline):
                    stopped_early = (f"stopped inside scope {index + 1} of "
                                     f"{len(planned)}: the run budget was spent")
                    break
                try:
                    store.save_insight(insights.generate(api, kind, scope))
                    warmed += 1
                    touched.append(f"{kind}:{label}")
                except AiError as exc:
                    errors.append(f"{kind} [{label}]: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{kind} [{label}]: {type(exc).__name__}: {exc}")
            if stopped_early:
                break
    except Exception as exc:  # noqa: BLE001 -- record, then re-raise
        store.finish_run(run_id, "failed", item_count=warmed, scopes=touched,
                         error_message=f"{type(exc).__name__}: {exc}")
        raise

    status = "success" if not errors else ("failed" if warmed == 0 else "success")
    detail = f"{warmed} narrative(s) across {len(planned)} scope(s)"
    if stopped_early:
        detail = f"{detail}; {stopped_early}"
    store.finish_run(
        run_id, status, item_count=warmed, scopes=touched, detail=detail,
        error_message="; ".join(errors[:5]) or None)
    return {"job": "insight_refresh", "status": status, "warmed": warmed,
            "scopes": touched, "errors": errors,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


def refresh_risk(api, trigger="cron", limit=RISK_LIMIT, deadline=None):
    """Re-score in-flight projects against the current vintage."""
    run_id = store.start_run("risk_refresh", trigger,
                             gateway.model_name(), gateway.provider_name())
    started = time.perf_counter()
    if deadline is None:
        deadline = deadline_from_now()

    try:
        vintage = (api.get("/mart/kpis") or {}).get("data_as_of")
        result = risk.score(api, limit=limit, deadline=deadline)
        stored = store.save_risk(result["scored"], data_as_of=vintage)
    except Exception as exc:  # noqa: BLE001 -- record, then re-raise
        store.finish_run(run_id, "failed",
                         error_message=f"{type(exc).__name__}: {exc}")
        raise

    errors = result.get("failures") or []
    status = "success" if stored else "failed"
    detail = f"{stored} of {result['considered']} in-flight project(s) scored"
    if result.get("stopped_early"):
        detail = f"{detail}; {result['stopped_early']}"
    store.finish_run(
        run_id, status, item_count=stored, detail=detail,
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
    # ONE deadline, shared. Given a budget each, the two jobs together can run
    # to twice it, which is how a 700s bound produced a run killed at 900s.
    deadline = deadline_from_now()
    return {"status": "ok",
            "jobs": [refresh_insights(api, trigger, deadline=deadline),
                     refresh_risk(api, trigger, deadline=deadline)]}


def local_api():
    """
    The governed API, in this process, over the whole portfolio.

    The HTTP path (`bi.client.Api`) asserts an identity with `X-Demo-User`, which
    `TRANSFEROPS_AUTH=enforce` refuses by design -- so on a real deployment it is
    not a slower way to run this job, it is a 401. This reaches the same governed
    route functions `POST /ai/refresh` reaches, through `api.ai_routes._LocalApi`:
    still no SQL in `ai/`, still the provenance envelope, still a closed route
    list. What it skips is the round trip and the identity assertion.

    The scope is set here because no middleware ran to set it. It is the one
    place in the job that widens what the database will return, which is why it
    is a line in an entry point rather than a default anywhere.
    """
    from api import auth, db
    from api.ai_routes import _LocalApi

    db.CURRENT_SCOPE.set(auth.SCHEDULED_JOB.scope)
    return _LocalApi()


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
    parser.add_argument("--in-process", action="store_true",
                        help="read through the governed routes in this process "
                             "rather than over HTTP. Required wherever "
                             "TRANSFEROPS_AUTH=enforce, which refuses the "
                             "asserted identity the HTTP path relies on. "
                             "Ignores --api and --identity.")
    parser.add_argument("--job", choices=["all", "insights", "risk"], default="all")
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    if args.in_process:
        api = local_api()
    else:
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
