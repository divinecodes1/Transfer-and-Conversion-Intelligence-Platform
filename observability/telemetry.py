"""
Transfer & Conversion Intelligence Platform :: platform telemetry.

A note on the endpoint path. Prometheus conventionally scrapes `/metrics`, but in
this domain "metrics" already means governed business KPIs -- `/metrics/cycle-time`
is a transfer metric, not a counter. Serving both meanings from the same prefix
would be exactly the naming collision this project exists to argue against, so
telemetry lives at `/observability/metrics` and the scrape config points there.

What is measured is chosen to answer the questions that decide whether the
platform is working, rather than whether the process is alive:

  pipeline    when did data last land, how long did it take, did the gates pass
  api         latency and errors per endpoint
  assistant   did it resolve the right metric, did it abstain, was it attacked,
              and -- the one that matters for "self-explaining" -- what share of
              questions the governed platform answered at all

That last one is the adoption signal. A reporting assistant nobody trusts enough
to ask is a failure however good its latency graph looks.
"""
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter,
                               Gauge, Histogram, generate_latest)

REGISTRY = CollectorRegistry()

# ---- API -------------------------------------------------------------------
API_REQUESTS = Counter(
    "transferops_api_requests_total", "Analytics API requests",
    ["endpoint", "status"], registry=REGISTRY)

API_LATENCY = Histogram(
    "transferops_api_request_seconds", "Analytics API request latency",
    ["endpoint"], registry=REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0))

# ---- Warehouse / pipeline --------------------------------------------------
WAREHOUSE_PROJECTS = Gauge(
    "transferops_warehouse_projects", "Projects visible in the warehouse",
    registry=REGISTRY)

DATA_FRESHNESS = Gauge(
    "transferops_data_freshness_days",
    "Age in days of the most recent project snapshot", registry=REGISTRY)

LAST_LOAD_TIMESTAMP = Gauge(
    "transferops_last_successful_load_timestamp",
    "Unix time of the last successful warehouse load", registry=REGISTRY)

LAST_LOAD_DURATION = Gauge(
    "transferops_last_load_duration_seconds", "Duration of the most recent load",
    registry=REGISTRY)

DQ_GATE_FAILURES = Gauge(
    "transferops_dq_gate_failures", "Failing data-quality gates on the last load",
    registry=REGISTRY)

# ---- Assistant -------------------------------------------------------------
AGENT_QUESTIONS = Counter(
    "transferops_agent_questions_total", "Questions put to the assistant",
    ["intent", "outcome"], registry=REGISTRY)

AGENT_LATENCY = Histogram(
    "transferops_agent_seconds", "End-to-end assistant answer latency",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0))

AGENT_METRIC_RESOLVED = Counter(
    "transferops_agent_metric_resolved_total",
    "Questions resolved to a governed metric", ["metric_code"], registry=REGISTRY)

AGENT_ABSTENTIONS = Counter(
    "transferops_agent_abstentions_total",
    "Questions the assistant declined rather than guessed", ["reason"],
    registry=REGISTRY)

AGENT_SECURITY_EVENTS = Counter(
    "transferops_agent_security_events_total",
    "Injection or action attempts refused", ["kind"], registry=REGISTRY)

AGENT_PROVENANCE = Counter(
    "transferops_agent_provenance_total",
    "Answers by whether they carried complete provenance", ["complete"],
    registry=REGISTRY)

AGENT_TOOL_CALLS = Counter(
    "transferops_agent_tool_calls_total", "Governed tool invocations",
    ["tool", "outcome"], registry=REGISTRY)


def render():
    """The scrape payload and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def refresh_warehouse_gauges(fetch):
    """
    Pull pipeline state from tr_gov.etl_run at scrape time.

    Deliberately read on demand rather than cached: these gauges describe the
    warehouse, not this process, and a second API replica must not report stale
    freshness just because it started earlier.
    """
    import datetime as _dt

    row = fetch(
        "SELECT finished_at, duration_ms, rows_loaded, dq_failed "
        "FROM tr_gov.etl_run WHERE status = 'SUCCESS' "
        "ORDER BY finished_at DESC LIMIT 1", scope="*")
    if row:
        r = row[0]
        if r["finished_at"]:
            LAST_LOAD_TIMESTAMP.set(r["finished_at"].timestamp())
        LAST_LOAD_DURATION.set((r["duration_ms"] or 0) / 1000.0)
        WAREHOUSE_PROJECTS.set(r["rows_loaded"] or 0)
        DQ_GATE_FAILURES.set(r["dq_failed"] or 0)

    fresh = fetch("SELECT MAX(snapshot_date) AS d FROM tr_core.fact_project_snapshot",
                  scope="*")
    if fresh and fresh[0]["d"]:
        DATA_FRESHNESS.set((_dt.date.today() - fresh[0]["d"]).days)
