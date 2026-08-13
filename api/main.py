"""
Transfer & Conversion Intelligence Platform :: read-only analytics API over the governed metric layer.

The one rule that shapes every endpoint here: **this service does not compute
metrics.** It selects from `tr_metric` and `tr_mart`, which are the single place a
KPI is defined. If a number needs to change, it changes in SQL, in version control,
once -- and the dashboards, this API and the future agent all move together. An API
that quietly re-derived "cycle time" in Python would recreate exactly the accreted
mess the project exists to replace, one layer higher up.

The corollary is that every metric response is an *envelope*: the numbers travel
with the registered definition, the population, the filters that were applied and
how fresh the data is. That makes an answer reproducible in the dashboard, and it
is the contract the agent will consume in place of writing its own SQL.

Run it:
    uvicorn api.main:app --reload
    http://127.0.0.1:8000/docs
"""
import os
import time

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from observability import logs, telemetry

from . import auth, catalogue, db

log = logs.configure("transferops.api")

app = FastAPI(
    title="Transfer & Conversion Intelligence Platform Analytics API",
    description="Read-only access to governed transfer-project performance metrics.",
    version="0.1.0",
)


@app.on_event("startup")
def _announce_auth_posture():
    """Demo mode is a deliberate downgrade, so it is never a silent condition."""
    auth.warn_if_demo_mode("analytics API")


@app.middleware("http")
async def scope_requests(request: Request, call_next):
    """
    Resolve identity once, before anything queries, and pin the caller's data
    scope for the rest of the request.

    Setting it here rather than inside each endpoint is the safety property: an
    endpoint cannot forget to apply entitlements, because it never applies them --
    the database does, from a value established before the handler runs.
    """
    # Probes need a database round-trip but must not require an end-user token.
    # The response contains no portfolio data; every user-facing route remains
    # behind resolve().
    if request.url.path == "/healthz":
        return await call_next(request)

    # One id for the whole request, continuing an upstream trace when there is
    # one, so a dashboard panel and the API call under it share a correlation id.
    request_id = logs.new_request_id(request.headers.get("x-request-id"))
    started = time.perf_counter()

    try:
        identity = auth.resolve(request)
    except HTTPException as exc:
        log.warning("request rejected", extra={
            "path": request.url.path, "status": exc.status_code,
            "reason": exc.detail})
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers={"X-Request-ID": request_id})
    request.state.identity = identity
    db.CURRENT_SCOPE.set(identity.scope)

    # Label by the route template, never the resolved path: bucketing on
    # /projects/T-017 would mint a new time series per project and blow up
    # cardinality for no analytical gain.
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path)
    telemetry.API_LATENCY.labels(endpoint=endpoint).observe(elapsed)
    telemetry.API_REQUESTS.labels(
        endpoint=endpoint, status=str(response.status_code)).inc()

    # The route template and the resolved identity, never the result rows.
    log.info("request", extra={
        "method": request.method, "endpoint": endpoint,
        "status": response.status_code, "duration_ms": round(elapsed * 1000, 1),
        "identity": identity.username, "auth_source": identity.source})
    response.headers["X-Request-ID"] = request_id
    return response


_web_origins = [
    origin.strip()
    for origin in os.environ.get("TRANSFEROPS_WEB_ORIGIN", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_web_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.get("/observability/metrics", tags=["service"], include_in_schema=False)
def prometheus_metrics():
    """
    Prometheus scrape target.

    Not at `/metrics`: in this platform that prefix already means governed
    business KPIs (`/metrics/cycle-time`), and serving counters from the same
    namespace would be precisely the naming collision the metric catalogue exists
    to prevent. The scrape config points here instead.
    """
    try:
        telemetry.refresh_warehouse_gauges(db.fetch)
    except Exception:
        # Telemetry must never take the API down with it.
        pass
    payload, content_type = telemetry.render()
    return Response(content=payload, media_type=content_type)


@app.get("/whoami", tags=["service"])
def whoami(request: Request):
    """Who the platform thinks you are and what you may see. Useful on its own,
    and the thing to show when demonstrating that two users get two answers."""
    return request.state.identity.as_dict()

# Whitelisted grouping dimensions. A request names a key; only the value -- a SQL
# fragment written here -- ever reaches the database.
GROUP_COLS = {
    "fiscal_year": "completion_fiscal_year",
    "transfer_type": "transfer_type",
    "portfolio": "portfolio",
    "complexity_class": "complexity_class",
    "source_site": "source_site",
    "target_site": "target_site",
}

# Not every source carries every dimension: the forecast-cycle-time view is at
# project/snapshot grain and has no completion fiscal year to group by.
FORECAST_CT_GROUPS = {"transfer_type": "transfer_type", "portfolio": "portfolio"}

# Where each governed metric is served. Published through /catalogue so a consumer
# -- notably the agent -- discovers both what a metric means and how to fetch it
# from the same authority, instead of carrying its own routing table that can rot.
SERVES = {
    "ACTUAL_TRANSFER_CYCLE_TIME":     "/metrics/cycle-time",
    "CYCLE_TIME_DISTRIBUTION":        "/metrics/cycle-time",
    "BASELINE_FINISH_DEVIATION_DAYS": "/metrics/schedule-drift",
    "COMPLETION_VARIANCE_DAYS":       "/metrics/completion-variance",
    "FORECAST_ERROR_DAYS":            "/metrics/forecast",
    "FORECAST_CYCLE_TIME":            "/metrics/forecast-cycle-time",
    "STAGE_CYCLE_TIME":               "/metrics/stage-cycle-time",
    "TRANSFER_THROUGHPUT":            "/metrics/portfolio",
    "ON_TIME_COMPLETION_RATE":        "/metrics/portfolio",
}

PERCENTILES = """
    COUNT(*)                                                    AS n,
    MIN({col})                                                  AS min_days,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col})          AS p25,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {col})          AS median,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col})          AS p75,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY {col})          AS p90,
    MAX({col})                                                   AS max_days
"""


def _group_expr(group_by, allowed=None):
    allowed = allowed or GROUP_COLS
    if group_by is None:
        return "'ALL'", ""
    if group_by not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"group_by must be one of {sorted(allowed)}",
        )
    col = allowed[group_by]
    return col, f"GROUP BY {col}"


def _distribution(metric_code, value_col, source, base_predicate,
                  filters, group_by, allowed_groups=None):
    """Percentile distribution of one governed column, grouped and filtered."""
    group_col, group_clause = _group_expr(group_by, allowed_groups)
    body, params = db.where(filters)
    rows = db.fetch(
        f"SELECT {group_col} AS group_value, "
        f"{PERCENTILES.format(col=value_col)} "
        f"FROM {source} "
        f"WHERE {base_predicate} AND {body} "
        f"{group_clause} ORDER BY 1",
        params,
    )
    total = sum(r["n"] for r in rows)
    return {
        **catalogue.provenance(metric_code, db.applied_filters(filters), n=total),
        "group_by": group_by,
        "series": rows,
    }


# ---------------------------------------------------------------------------
@app.get("/health", tags=["service"])
def health():
    """Liveness plus a real warehouse round-trip -- a service that cannot reach
    the metric layer is not healthy, whatever the process is doing."""
    try:
        row = db.fetch_one("SELECT COUNT(*) AS n FROM tr_core.dim_project")
        return {"status": "healthy", "projects": row["n"], "data_as_of": db.data_as_of()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"warehouse unreachable: {exc}")


@app.get("/healthz", tags=["service"], include_in_schema=False)
def healthz():
    """Public probe: verify process and warehouse connectivity without data."""
    try:
        db.fetch_one("SELECT 1 AS ok")
        return {"status": "healthy"}
    except Exception:
        raise HTTPException(status_code=503, detail="warehouse unreachable")


# ---- The catalogue --------------------------------------------------------
@app.get("/catalogue", tags=["catalogue"])
def list_catalogue():
    """Every governed metric definition, each with the endpoint that serves it.
    This is what the agent resolves against instead of guessing what a user
    means by "late"."""
    return {"metrics": [{**m, "endpoint": SERVES.get(m["metric_code"])}
                        for m in catalogue.all_metrics()]}


@app.get("/catalogue/{metric_code}", tags=["catalogue"])
def get_metric_definition(metric_code: str):
    code = metric_code.upper()
    return {**catalogue.get(code), "endpoint": SERVES.get(code)}


# ---- Metrics --------------------------------------------------------------
@app.get("/metrics/cycle-time", tags=["metrics"])
def cycle_time(
    group_by: str | None = Query("fiscal_year", description=f"one of {sorted(GROUP_COLS)}"),
    fiscal_year: int | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity_class: str | None = None,
):
    """
    Cycle-time distribution -- the box-plot source. Percentiles rather than a mean,
    because the spread across fiscal years is the thing the original reporting
    actually showed.
    """
    return _distribution(
        "CYCLE_TIME_DISTRIBUTION", "actual_cycle_time_days",
        "tr_metric.v_project_kpi", "actual_cycle_time_days IS NOT NULL",
        {"completion_fiscal_year": fiscal_year, "transfer_type": transfer_type,
         "portfolio": portfolio, "complexity_class": complexity_class},
        group_by,
    )


@app.get("/metrics/schedule-drift", tags=["metrics"])
def schedule_drift(
    group_by: str | None = Query("transfer_type"),
    status: str | None = None,
    fiscal_year: int | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
):
    """
    Original vs latest schedule: how far the plan has moved from the frozen
    baseline. Auditable because baseline and latest come from separate rows of
    `fact_schedule_revision`, never from an overwritten column.
    """
    return _distribution(
        "BASELINE_FINISH_DEVIATION_DAYS", "schedule_deviation_days",
        "tr_metric.v_project_kpi", "schedule_deviation_days IS NOT NULL",
        {"status": status, "completion_fiscal_year": fiscal_year,
         "transfer_type": transfer_type, "portfolio": portfolio},
        group_by,
    )


@app.get("/metrics/completion-variance", tags=["metrics"])
def completion_variance(
    group_by: str | None = Query("fiscal_year"),
    fiscal_year: int | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
):
    """How far completed projects landed from their frozen baseline -- realised
    deviation, as opposed to the drift a still-open plan has accumulated."""
    return _distribution(
        "COMPLETION_VARIANCE_DAYS", "completion_variance_days",
        "tr_metric.v_project_kpi", "completion_variance_days IS NOT NULL",
        {"completion_fiscal_year": fiscal_year, "transfer_type": transfer_type,
         "portfolio": portfolio},
        group_by,
    )


@app.get("/metrics/forecast-cycle-time", tags=["metrics"])
def forecast_cycle_time(
    group_by: str | None = Query("transfer_type"),
    transfer_type: str | None = None,
    portfolio: str | None = None,
):
    """Expected duration as believed at each snapshot -- the forward-looking twin
    of actual cycle time, and the "forecast vs history" comparison in one place."""
    return _distribution(
        "FORECAST_CYCLE_TIME", "forecast_cycle_time_days",
        "tr_metric.v_forecast_cycle_time", "forecast_cycle_time_days IS NOT NULL",
        {"transfer_type": transfer_type, "portfolio": portfolio},
        group_by, allowed_groups=FORECAST_CT_GROUPS,
    )


@app.get("/metrics/forecast", tags=["metrics"])
def forecast_accuracy(
    transfer_type: str | None = None,
    portfolio: str | None = None,
):
    """
    Forecast error bucketed by how far *before* completion the forecast was made.

    This is deliberately not "how accurate was the latest forecast?". Measured that
    way an organisation looks excellent simply by revising its forecast days before
    the finish. Bucketing by horizon exposes that, and the snapshot history is what
    makes it computable at all.
    """
    filters = {"p.transfer_type": transfer_type, "p.portfolio": portfolio}
    body, params = db.where(filters)
    rows = db.fetch(
        """
        SELECT CASE WHEN f.horizon_days >= 90 THEN '90+'
                    WHEN f.horizon_days >= 60 THEN '60-89'
                    WHEN f.horizon_days >= 30 THEN '30-59'
                    ELSE '0-29' END                                   AS horizon_bucket,
               COUNT(*)                                               AS n,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY f.abs_forecast_error_days)                 AS median_abs_error,
               PERCENTILE_CONT(0.90) WITHIN GROUP (
                   ORDER BY f.abs_forecast_error_days)                 AS p90_abs_error,
               AVG(f.forecast_error_days)                             AS bias
        FROM   tr_metric.v_forecast_error f
        JOIN   tr_core.dim_project p USING (project_key)
        WHERE  f.horizon_days >= 0 AND """ + body + """
        GROUP BY 1
        ORDER BY MIN(f.horizon_days)
        """,
        params,
    )
    return {
        **catalogue.provenance("FORECAST_ERROR_DAYS", db.applied_filters(filters),
                               n=sum(r["n"] for r in rows)),
        "note": ("bias > 0 means the project finished later than forecast "
                 "(optimistic); horizon_days is measured back from actual finish"),
        "series": rows,
    }


@app.get("/metrics/stage-cycle-time", tags=["metrics"])
def stage_cycle_time():
    """Milestone-to-milestone durations -- where in the transfer process the
    delay is actually created, rather than only that the total is large."""
    rows = db.fetch(
        """
        SELECT from_stage, to_stage, COUNT(*) AS n,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY stage_cycle_time_days) AS median,
               PERCENTILE_CONT(0.90) WITHIN GROUP (
                   ORDER BY stage_cycle_time_days) AS p90
        FROM   tr_metric.v_stage_cycle_time
        GROUP  BY from_stage, to_stage, from_seq
        ORDER  BY from_seq
        """
    )
    return {**catalogue.provenance("STAGE_CYCLE_TIME", {}), "series": rows}


@app.get("/metrics/portfolio", tags=["metrics"])
def portfolio_period(
    fiscal_year: int | None = None,
    portfolio: str | None = None,
):
    """Management rollup by fiscal period: throughput, on-time rate, median cycle
    time, average completion variance. Straight from the mart -- no recomputation."""
    filters = {"fiscal_year": fiscal_year, "portfolio": portfolio}
    body, params = db.where(filters)
    rows = db.fetch(
        f"SELECT * FROM tr_mart.mart_portfolio_period WHERE {body} "
        f"ORDER BY fiscal_year, portfolio",
        params,
    )
    return {
        **catalogue.provenance(
            ["TRANSFER_THROUGHPUT", "ON_TIME_COMPLETION_RATE",
             "ACTUAL_TRANSFER_CYCLE_TIME", "COMPLETION_VARIANCE_DAYS"],
            db.applied_filters(filters)),
        "series": rows,
    }


# ---- Projects -------------------------------------------------------------
@app.get("/projects", tags=["projects"])
def list_projects(
    status: str | None = None,
    portfolio: str | None = None,
    transfer_type: str | None = None,
    source_site: str | None = None,
    target_site: str | None = None,
    health: str | None = Query(None, description="ON_TRACK | AT_RISK | LATE | UNKNOWN"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Open portfolio with its live slip and health band.

    Health comes from `mart_project_status`, where the thresholds are defined once
    in SQL. The API deliberately does not band the drift itself -- a second set of
    thresholds living in Python is how two dashboards start disagreeing.
    """
    filters = {"status": status, "portfolio": portfolio,
               "transfer_type": transfer_type, "source_site": source_site,
               "target_site": target_site, "health": health}
    body, params = db.where(filters)
    rows = db.fetch(
        f"SELECT * FROM tr_mart.mart_project_status WHERE {body} "
        f"ORDER BY schedule_deviation_days DESC NULLS LAST "
        f"LIMIT %s OFFSET %s",
        params + [limit, offset],
    )
    total = db.fetch_one(
        f"SELECT COUNT(*) AS n FROM tr_mart.mart_project_status WHERE {body}", params)
    return {
        "filters_applied": db.applied_filters(filters),
        "data_as_of": db.data_as_of(),
        "total_matching": total["n"],
        "limit": limit,
        "offset": offset,
        "projects": rows,
    }


# ---- The mart layer -------------------------------------------------------
# One filter contract, one grain, six views onto it.
#
# Everything below reads `tr_mart.mart_project_register` -- project grain, every
# governed column, the health band defined once in SQL -- and aggregates it with
# the same whitelisted-column composer the distribution endpoints already use.
# The rule the rest of this file follows still holds: no business rule is
# declared here. On-time, health, replan and WIP age all arrive already computed;
# this layer counts and takes percentiles of them, and nothing else.
#
# These exist because a filtered rollup cannot be a view: aggregation that has
# already happened cannot be filtered afterwards, and every screen filters.

REGISTER = "tr_mart.mart_project_register"

# The public filter name -> the SQL fragment it scopes. Keys arrive from a
# request; only the values -- written here -- ever reach the database.
MART_FILTERS = {
    "fiscal_year": "completion_fiscal_year",
    "transfer_type": "transfer_type",
    "portfolio": "portfolio",
    "complexity": "complexity_class",
    "status": "status",
    "health": "health",
    "source_site": "source_site",
    "target_site": "target_site",
}


def _mart_where(filters, site=None):
    """
    The WHERE body for one filter scope, plus the parameters it binds.

    `site` is the one filter that is not a column: a site is relevant to a
    project whether the transfer left it or arrived at it, so it matches either
    end. Collapsing that into "target_site" would quietly hide every outbound
    transfer from the site lead who asked about their own site.
    """
    spec = {MART_FILTERS[k]: v for k, v in filters.items()
            if k in MART_FILTERS and v is not None}
    body, params = db.where(spec)
    if site:
        body = f"({body}) AND (source_site = %s OR target_site = %s)"
        params = params + [site, site]
    return body, params


def _applied(filters, site=None):
    applied = {k: v for k, v in filters.items() if v is not None}
    if site:
        applied["site"] = site
    return applied


MART_METRICS = ["TRANSFER_THROUGHPUT", "ON_TIME_COMPLETION_RATE",
                "ACTUAL_TRANSFER_CYCLE_TIME", "BASELINE_FINISH_DEVIATION_DAYS",
                "REPLAN_RATE", "WIP_AGE_DAYS", "PORTFOLIO_WIP"]


@app.get("/mart/kpis", tags=["mart"])
def mart_kpis(
    fiscal_year: int | None = None,
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
):
    """
    The headline tiles, for one filter scope.

    Every figure is an aggregate of a column the metric layer already defined.
    `delayed_count` counts the health band rather than re-applying a day
    threshold here -- that threshold lives in `mart_project_register` and is read
    by the register table, the risk scorer and this rollup from the one place.
    """
    filters = {"fiscal_year": fiscal_year, "transfer_type": transfer_type,
               "portfolio": portfolio, "complexity": complexity}
    body, params = _mart_where(filters, site)
    row = db.fetch_one(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE status = 'COMPLETED')            AS throughput,
            COUNT(*) FILTER (WHERE wip_age_days IS NOT NULL)        AS wip,
            PERCENTILE_CONT(0.50) WITHIN GROUP (
                ORDER BY actual_cycle_time_days)                    AS median_cycle_time,
            PERCENTILE_CONT(0.90) WITHIN GROUP (
                ORDER BY actual_cycle_time_days)                    AS p90_cycle_time,
            -- Rates are counted over the population the metric is *defined*
            -- for, not over every row in scope. `CASE WHEN on_time THEN 100
            -- ELSE 0` looks equivalent and is not: the ELSE swallows the NULL
            -- that an in-flight project carries, and every unfinished project
            -- silently scores as "missed its baseline". That reads as a
            -- collapsing on-time rate whenever the portfolio takes on work.
            100.0 * COUNT(*) FILTER (WHERE on_time)
                  / NULLIF(COUNT(*) FILTER (WHERE on_time IS NOT NULL), 0)
                                                                    AS on_time_rate,
            100.0 * COUNT(*) FILTER (WHERE was_replanned)
                  / NULLIF(COUNT(*) FILTER (WHERE was_replanned IS NOT NULL), 0)
                                                                    AS replan_rate,
            PERCENTILE_CONT(0.50) WITHIN GROUP (
                ORDER BY wip_age_days)                              AS median_wip_age,
            PERCENTILE_CONT(0.50) WITHIN GROUP (
                ORDER BY schedule_deviation_days)                   AS median_schedule_deviation,
            COUNT(*) FILTER (WHERE health = 'LATE')                 AS delayed_count,
            COUNT(*)                                                AS total_projects
        FROM {REGISTER}
        WHERE {body}
        """,
        params,
    )
    return {
        **catalogue.provenance(MART_METRICS, _applied(filters, site),
                               n=(row or {}).get("total_projects", 0)),
        "kpis": row or {},
    }


@app.get("/mart/trend", tags=["mart"])
def mart_trend(
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
):
    """Fiscal-year trend: throughput, median cycle time, on-time and replan rate.

    Not filtered by fiscal year, by design -- a trend line with one point on it
    is a number wearing a chart's clothes."""
    filters = {"transfer_type": transfer_type, "portfolio": portfolio,
               "complexity": complexity}
    body, params = _mart_where(filters, site)
    rows = db.fetch(
        f"""
        SELECT completion_fiscal_year                               AS fiscal_year,
               COUNT(*)                                             AS throughput,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)                 AS median_cycle_time,
               -- Same population guard as /mart/kpis: a completed project with
               -- no valid baseline has no on-time answer, and counting it as a
               -- miss would understate every year it appears in.
               100.0 * COUNT(*) FILTER (WHERE on_time)
                     / NULLIF(COUNT(*) FILTER (WHERE on_time IS NOT NULL), 0)
                                                                    AS on_time_rate,
               100.0 * COUNT(*) FILTER (WHERE was_replanned)
                     / NULLIF(COUNT(*) FILTER (WHERE was_replanned IS NOT NULL), 0)
                                                                    AS replan_rate
        FROM   {REGISTER}
        WHERE  status = 'COMPLETED' AND completion_fiscal_year IS NOT NULL
          AND  {body}
        GROUP  BY completion_fiscal_year
        ORDER  BY completion_fiscal_year
        """,
        params,
    )
    return {
        **catalogue.provenance(
            ["TRANSFER_THROUGHPUT", "ON_TIME_COMPLETION_RATE",
             "ACTUAL_TRANSFER_CYCLE_TIME", "REPLAN_RATE"],
            _applied(filters, site), n=sum(r["throughput"] for r in rows)),
        "series": rows,
    }


# The cohorts a distribution may be cut by. A request names a key; the SQL
# fragment it maps to is written here and nowhere else.
COHORTS = {
    "transfer_type": "transfer_type",
    "complexity_class": "complexity_class",
    "target_site": "target_site",
    "source_site": "source_site",
    "portfolio": "portfolio",
    "fiscal_year": "completion_fiscal_year",
}


@app.get("/mart/distribution", tags=["mart"])
def mart_distribution(
    group_by: str = Query("transfer_type", description=f"one of {sorted(COHORTS)}"),
    fiscal_year: int | None = None,
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
):
    """Cycle-time spread per cohort -- the box-plot source, filter-scoped."""
    if group_by not in COHORTS:
        raise HTTPException(status_code=400,
                            detail=f"group_by must be one of {sorted(COHORTS)}")
    filters = {"fiscal_year": fiscal_year, "transfer_type": transfer_type,
               "portfolio": portfolio, "complexity": complexity}
    body, params = _mart_where(filters, site)
    rows = db.fetch(
        f"""
        SELECT CAST({COHORTS[group_by]} AS VARCHAR)                  AS cohort,
               COUNT(*)                                              AS n,
               MIN(actual_cycle_time_days)                           AS min_days,
               PERCENTILE_CONT(0.25) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)                  AS p25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)                  AS p50,
               PERCENTILE_CONT(0.75) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)                  AS p75,
               PERCENTILE_CONT(0.90) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)                  AS p90,
               MAX(actual_cycle_time_days)                           AS max_days
        FROM   {REGISTER}
        WHERE  actual_cycle_time_days IS NOT NULL AND {body}
        GROUP  BY {COHORTS[group_by]}
        ORDER  BY 1
        """,
        params,
    )
    for r in rows:
        r["iqr"] = None if r["p75"] is None or r["p25"] is None else r["p75"] - r["p25"]
    return {
        **catalogue.provenance("CYCLE_TIME_DISTRIBUTION", _applied(filters, site),
                               n=sum(r["n"] for r in rows)),
        "group_by": group_by,
        "series": rows,
    }


@app.get("/mart/accuracy", tags=["mart"])
def mart_accuracy(
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
):
    """
    Forecast quality by how far ahead the forecast was made.

    The horizon buckets and the 14-day hit threshold both come from
    `tr_metric.v_forecast_error_horizon`, so this endpoint and the PMO horizon
    curve cannot disagree about what "within 14 days" means.
    """
    filters = {"transfer_type": transfer_type, "portfolio": portfolio,
               "complexity": complexity}
    body, params = _mart_where(filters, site)
    rows = db.fetch(
        f"""
        SELECT h.horizon_bucket,
               MIN(h.horizon_floor)                                  AS horizon_days,
               COUNT(*)                                              AS n,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY h.forecast_error_days)                   AS median_error,
               AVG(h.forecast_error_days)                            AS bias,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY h.abs_forecast_error_days)               AS median_abs_error,
               PERCENTILE_CONT(0.90) WITHIN GROUP (
                   ORDER BY h.abs_forecast_error_days)               AS p90_abs_error,
               AVG(CASE WHEN h.within_14_days THEN 100.0 ELSE 0.0 END)
                                                                     AS within_14_days_pct
        FROM   tr_metric.v_forecast_error_horizon h
        JOIN   {REGISTER} r USING (project_key)
        WHERE  {body}
        GROUP  BY h.horizon_bucket
        ORDER  BY MIN(h.horizon_floor)
        """,
        params,
    )
    return {
        **catalogue.provenance("FORECAST_ERROR_DAYS", _applied(filters, site),
                               n=sum(r["n"] for r in rows)),
        "note": ("bias > 0 means the project finished later than forecast "
                 "(the forecast was optimistic)"),
        "series": rows,
    }


SORTABLE = {"actual_cycle_time_days", "schedule_deviation_days",
            "completion_variance_days", "revision_count", "wip_age_days",
            "project_id", "health"}


@app.get("/mart/projects", tags=["mart"])
def mart_projects(
    fiscal_year: int | None = None,
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
    status: str | None = None,
    health: str | None = None,
    search: str | None = None,
    sort_by: str | None = Query(None, description=f"one of {sorted(SORTABLE)}"),
    descending: bool = True,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """The project register: governed rows at project grain, filtered and sorted."""
    filters = {"fiscal_year": fiscal_year, "transfer_type": transfer_type,
               "portfolio": portfolio, "complexity": complexity,
               "status": status, "health": health}
    body, params = _mart_where(filters, site)

    if search:
        # Parameterised, and matched against three named columns rather than a
        # caller-chosen one: a search box is the most obvious place for a column
        # name to arrive from a request, so it never does.
        body += (" AND (LOWER(project_id) LIKE %s OR LOWER(project_name) LIKE %s "
                 "OR LOWER(target_site) LIKE %s)")
        needle = f"%{search.lower()}%"
        params = params + [needle, needle, needle]

    if sort_by and sort_by not in SORTABLE:
        raise HTTPException(status_code=400,
                            detail=f"sort_by must be one of {sorted(SORTABLE)}")
    order = (f"{sort_by} {'DESC' if descending else 'ASC'} NULLS LAST"
             if sort_by else "schedule_deviation_days DESC NULLS LAST")

    rows = db.fetch(
        f"SELECT * FROM {REGISTER} WHERE {body} ORDER BY {order}, project_id "
        f"LIMIT %s OFFSET %s", params + [limit, offset])
    total = db.fetch_one(
        f"SELECT COUNT(*) AS n FROM {REGISTER} WHERE {body}", params)

    return {
        **catalogue.provenance(MART_METRICS,
                               _applied({**filters, "search": search}, site),
                               n=(total or {}).get("n", 0)),
        "total_matching": (total or {}).get("n", 0),
        "limit": limit,
        "offset": offset,
        "projects": rows,
    }


@app.get("/pipeline/runs", tags=["service"])
def pipeline_runs(limit: int = Query(50, ge=1, le=200)):
    """
    Load history: when the warehouse last refreshed, how long it took, and how
    many quality gates passed.

    "When did this data last load?" is the first question anyone asks when a
    dashboard looks wrong, and it is not answerable from the warehouse contents
    alone -- a table full of rows cannot say when they arrived, or whether the
    run that produced them also failed three gates. `tr_gov.etl_run` is one of
    the two tables that survive a rebuild for exactly that reason.
    """
    return {"runs": db.fetch(
        "SELECT run_id, engine, started_at, finished_at, duration_ms, rows_loaded, "
        "       dq_passed, dq_failed, status "
        "FROM tr_gov.etl_run ORDER BY started_at DESC LIMIT %s", [limit])}


@app.get("/mart/filter-options", tags=["mart"])
def mart_filter_options():
    """
    The filter vocabulary, derived from the data the caller may see.

    Entitlement-scoped like everything else, which is the useful part: you cannot
    enumerate a portfolio you are not allowed to read, so the dropdown itself
    never leaks the shape of the wider estate.
    """
    rows = db.fetch(
        "SELECT dimension, value FROM tr_mart.mart_filter_options "
        "ORDER BY dimension, value")
    options = {}
    for row in rows:
        options.setdefault(row["dimension"], []).append(row["value"])
    return {"data_as_of": db.data_as_of(), "options": options}


# ---- Readiness, network and similarity ------------------------------------
# Three capabilities, one rule, unchanged: this module selects, it never
# computes. Every number below is a column of a view in sql/13, so the readiness
# weighting, the band boundaries and the similarity weights are all things a
# reader can find in one file rather than reconstruct from Python.

READINESS_REGISTER = "tr_mart.mart_readiness_register"

# Readiness deliberately has no fiscal_year filter: it only exists for work that
# has not completed, so filtering it by completion year would return an empty
# screen and read as a bug rather than a category error.
READINESS_FILTERS = {
    "transfer_type": "transfer_type",
    "portfolio": "portfolio",
    "complexity": "complexity_class",
    "status": "status",
    "band": "readiness_band",
    "source_site": "source_site",
    "target_site": "target_site",
}

READINESS_METRICS = ["TRANSFER_READINESS_SCORE", "READINESS_DIMENSION_SCORE"]
NETWORK_METRICS = ["ACTUAL_TRANSFER_CYCLE_TIME", "ON_TIME_COMPLETION_RATE",
                   "BASELINE_FINISH_DEVIATION_DAYS", "TRANSFER_READINESS_SCORE",
                   "ROUTE_BOTTLENECK_STAGE"]
SIMILARITY_METRICS = ["TRANSFER_SIMILARITY_SCORE", "ACTUAL_TRANSFER_CYCLE_TIME",
                      "COMPLETION_VARIANCE_DAYS"]


def _readiness_where(filters, site=None):
    """As `_mart_where`, over the readiness vocabulary. Values bind; keys never."""
    spec = {READINESS_FILTERS[k]: v for k, v in filters.items()
            if k in READINESS_FILTERS and v is not None}
    body, params = db.where(spec)
    if site:
        body = f"({body}) AND (source_site = %s OR target_site = %s)"
        params = params + [site, site]
    return body, params


@app.get("/readiness", tags=["readiness"])
def readiness(
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
    status: str | None = None,
    band: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Transfer readiness for the in-flight portfolio, worst first.

    Ordered ascending on purpose: this screen exists to answer "where does
    management need to act?", and a list that opens on the healthiest transfers
    answers a question nobody asked.
    """
    filters = {"transfer_type": transfer_type, "portfolio": portfolio,
               "complexity": complexity, "status": status, "band": band}
    body, params = _readiness_where(filters, site)

    summary = db.fetch_one(
        f"""
        SELECT COUNT(*)                                        AS projects,
               AVG(readiness_pct)                              AS avg_readiness_pct,
               COUNT(*) FILTER (WHERE readiness_band = 'READY')     AS ready_count,
               COUNT(*) FILTER (WHERE readiness_band = 'AT_RISK')   AS at_risk_count,
               COUNT(*) FILTER (WHERE readiness_band = 'NOT_READY') AS not_ready_count,
               -- Assessment age is the honesty column: a readiness score nobody
               -- has revisited in four months is not evidence about today.
               AVG(assessment_age_days)                        AS avg_assessment_age_days
        FROM   {READINESS_REGISTER} WHERE {body}
        """, params)

    rows = db.fetch(
        f"SELECT * FROM {READINESS_REGISTER} WHERE {body} "
        f"ORDER BY readiness_pct ASC, project_id LIMIT %s", params + [limit])

    return {
        **catalogue.provenance(READINESS_METRICS, _applied(filters, site),
                               n=(summary or {}).get("projects", 0)),
        "summary": summary or {},
        "projects": rows,
    }


@app.get("/readiness/dimensions", tags=["readiness"])
def readiness_dimensions(
    site: str | None = None,
    transfer_type: str | None = None,
    portfolio: str | None = None,
    complexity: str | None = None,
):
    """
    Portfolio readiness broken down by dimension, weakest first.

    This is what makes "qualification is the bottleneck" a number rather than an
    assertion: the weakest dimension across the whole in-flight portfolio is read
    off the same rows that score each individual project.
    """
    filters = {"transfer_type": transfer_type, "portfolio": portfolio,
               "complexity": complexity}
    spec = {READINESS_FILTERS[k]: v for k, v in filters.items()
            if k in READINESS_FILTERS and v is not None}
    body, params = db.where(spec)
    if site:
        body = f"({body}) AND (source_site = %s OR target_site = %s)"
        params = params + [site, site]

    rows = db.fetch(
        f"""
        SELECT dimension_code, dimension_name, weight_pct, sequence_no,
               AVG(score_pct)                          AS avg_score_pct,
               MIN(score_pct)                          AS min_score_pct,
               COUNT(*)                                AS projects,
               COUNT(*) FILTER (WHERE score_pct < 70)  AS below_70
        FROM   tr_mart.mart_readiness_dimension
        WHERE  {body}
        GROUP  BY dimension_code, dimension_name, weight_pct, sequence_no
        ORDER  BY avg_score_pct ASC
        """, params)

    return {
        **catalogue.provenance(READINESS_METRICS, _applied(filters, site)),
        "dimensions": rows,
    }


@app.get("/network", tags=["network"])
def network(min_transfers: int = Query(1, ge=1, le=100)):
    """
    The site-to-site transfer network: one row per lane, plus per-site totals.

    Every lane figure is an existing registered metric re-grained onto the route
    -- no new definition of "on time" appears here just because the question is
    now about a lane rather than a project.
    """
    lanes = db.fetch(
        "SELECT * FROM tr_mart.mart_transfer_network "
        "WHERE total_transfers >= %s "
        "ORDER BY total_transfers DESC, source_site, target_site", [min_transfers])
    sites = db.fetch(
        "SELECT site, direction, transfers, active_transfers "
        "FROM tr_mart.mart_site_flow ORDER BY site, direction")
    return {
        **catalogue.provenance(NETWORK_METRICS, {"min_transfers": min_transfers},
                               n=len(lanes)),
        "lanes": lanes,
        "sites": sites,
    }


@app.get("/projects/{project_id}/readiness", tags=["readiness"])
def project_readiness(project_id: str):
    """One project's readiness, dimension by dimension, with the weights applied."""
    overall = db.fetch_one(
        f"SELECT * FROM {READINESS_REGISTER} WHERE project_id = %s", [project_id])
    if overall is None:
        # A completed or cancelled project is not an error, it is a project that
        # legitimately has no readiness -- so say which, rather than 404-ing on a
        # project the caller can plainly see elsewhere in the console.
        exists = db.fetch_one(
            "SELECT status FROM tr_core.dim_project WHERE project_id = %s", [project_id])
        if exists is None:
            raise HTTPException(status_code=404, detail=f"no project {project_id}")
        return {
            **catalogue.provenance(READINESS_METRICS, {"project_id": project_id}),
            "assessed": False,
            "reason": f"readiness is assessed for in-flight transfers; "
                      f"{project_id} is {exists['status']}",
            "overall": None,
            "dimensions": [],
        }

    return {
        **catalogue.provenance(READINESS_METRICS, {"project_id": project_id}),
        "assessed": True,
        "overall": overall,
        "dimensions": db.fetch(
            "SELECT dimension_code, dimension_name, weight_pct, sequence_no, "
            "       score_pct, assessed_on "
            "FROM   tr_metric.v_project_readiness_dimension "
            "WHERE  project_id = %s ORDER BY sequence_no", [project_id]),
    }


@app.get("/projects/{project_id}/similar", tags=["similarity"])
def project_similar(
    project_id: str,
    limit: int = Query(5, ge=1, le=25),
    min_similarity: int = Query(50, ge=0, le=100),
):
    """
    Completed transfers that resemble this one, and what happened to them.

    The outcome summary is the payload: three similar transfers that each ran
    twelve days over is a pattern worth acting on, and a similarity score with no
    outcome attached is trivia. Both halves travel together for that reason.
    """
    key = db.fetch_one(
        "SELECT project_key, status FROM tr_core.dim_project WHERE project_id = %s",
        [project_id])
    if key is None:
        raise HTTPException(status_code=404, detail=f"no project {project_id}")

    rows = db.fetch(
        "SELECT * FROM tr_mart.mart_similar_transfers "
        "WHERE project_key = %s AND similarity_pct >= %s "
        "ORDER BY similarity_pct DESC, similar_project_id LIMIT %s",
        [key["project_key"], min_similarity, limit])

    # Computed over the returned neighbours, not over the whole history: the
    # summary has to describe the cases actually shown, or the console displays
    # three projects beside a median drawn from thirty.
    outcome = db.fetch_one(
        """
        SELECT COUNT(*)                                   AS n,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY completion_variance_days)     AS median_variance_days,
               PERCENTILE_CONT(0.50) WITHIN GROUP (
                   ORDER BY actual_cycle_time_days)       AS median_cycle_time_days,
               100.0 * COUNT(*) FILTER (WHERE on_time)
                     / NULLIF(COUNT(*) FILTER (WHERE on_time IS NOT NULL), 0)
                                                          AS on_time_rate
        FROM (
            SELECT * FROM tr_mart.mart_similar_transfers
            WHERE project_key = %s AND similarity_pct >= %s
            ORDER BY similarity_pct DESC, similar_project_id LIMIT %s
        ) s
        """, [key["project_key"], min_similarity, limit])

    return {
        **catalogue.provenance(SIMILARITY_METRICS,
                               {"project_id": project_id,
                                "min_similarity": min_similarity},
                               n=len(rows)),
        "reference_status": key["status"],
        "outcome": outcome or {},
        "similar": rows,
    }


@app.get("/projects/{project_id}", tags=["projects"])
def project_detail(project_id: str):
    """
    One project, answerable as it was known at any point in time.

    The schedule revisions and snapshots are the reason this is possible: the
    baseline is immutable and every replan is kept, so "what did we believe three
    months ago?" is a query rather than a lost fact.
    """
    kpi = db.fetch_one(
        "SELECT * FROM tr_metric.v_project_kpi WHERE project_id = %s", [project_id])
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"no project {project_id}")
    key = kpi["project_key"]

    return {
        "data_as_of": db.data_as_of(),
        "project": kpi,
        "schedule_revisions": db.fetch(
            "SELECT revision_id, revision_timestamp, revision_reason, planned_start, "
            "       planned_finish, forecast_finish, is_baseline "
            "FROM   tr_core.fact_schedule_revision WHERE project_key = %s "
            "ORDER  BY revision_timestamp, revision_id", [key]),
        "milestones": db.fetch(
            "SELECT m.milestone_code, m.milestone_name, m.sequence_no, "
            "       e.planned_date, e.actual_date, e.event_status "
            "FROM   tr_core.fact_milestone_event e "
            "JOIN   tr_core.dim_milestone m USING (milestone_key) "
            "WHERE  e.project_key = %s ORDER BY m.sequence_no", [key]),
        "snapshots": db.fetch(
            "SELECT snapshot_date, status, forecast_finish "
            "FROM   tr_core.fact_project_snapshot WHERE project_key = %s "
            "ORDER  BY snapshot_date", [key]),
    }


# ---- The AI surface -------------------------------------------------------
# Imported last, and at the bottom: ai_routes reaches back into this module for
# the governed mart functions, so they have to exist by the time it is imported.
# The whole AI layer is optional -- a deployment with no model configured still
# serves every endpoint above, and /ai/status says plainly that it is switched
# off rather than failing at import.
from .ai_routes import router as ai_router  # noqa: E402

app.include_router(ai_router)
