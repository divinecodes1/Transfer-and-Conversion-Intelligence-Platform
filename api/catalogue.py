"""
Transfer & Conversion Intelligence Platform :: the metric catalogue, served.

`tr_gov.metric_definition` already holds one governed definition per KPI. This
module makes it the API's own source of truth for what a metric *means*, so that
a number and its definition can never be served separately.

That is the whole point of the envelope in `provenance()`: an answer travels with
the definition it was computed from, the population it covers, the filters that
were applied, and how fresh the data is. A manager can reproduce it in the
dashboard; the agent, later, has nothing left to invent.
"""
import os
import threading
import time

from fastapi import HTTPException

from . import db

_CATALOGUE_SQL = """
SELECT metric_code, business_name, definition, grain, unit,
       population, exclusions, owner, version, effective_from
FROM   tr_gov.metric_definition
"""

# Every metric response carries its definitions, so an uncached catalogue means a
# lookup per metric per request -- four extra round trips on the portfolio rollup
# alone. The catalogue changes when someone deploys a new metric version, not
# between requests, so a short TTL costs nothing and removes the N+1. It is a
# cache with an expiry rather than a load-once constant because a definition
# change should reach a running service without a restart.
_TTL_SECONDS = int(os.environ.get("TRANSFEROPS_CATALOGUE_TTL", "60"))
_CACHE = {"rows": None, "at": 0.0}
_LOCK = threading.Lock()


def _catalogue():
    now = time.time()
    with _LOCK:
        if _CACHE["rows"] is None or now - _CACHE["at"] > _TTL_SECONDS:
            _CACHE["rows"] = db.fetch(_CATALOGUE_SQL + " ORDER BY metric_code")
            _CACHE["at"] = now
        return _CACHE["rows"]


def invalidate():
    """Drop the cached catalogue -- for tests and for a post-deploy refresh."""
    with _LOCK:
        _CACHE["rows"] = None


def all_metrics():
    return list(_catalogue())


def get(metric_code):
    row = next((m for m in _catalogue() if m["metric_code"] == metric_code), None)
    if row is None:
        # A metric that is served but not registered would be exactly the drift
        # tests/governance_checks.py exists to prevent, so fail loudly.
        raise HTTPException(
            status_code=500,
            detail=f"{metric_code} is not registered in tr_gov.metric_definition",
        )
    return row


def provenance(metric_code, filters, n=None):
    """
    Wrap a result set in the definition(s) and scope it was produced under.

    `metric_code` may be a single code or several, because a rollup like the
    portfolio period mart legitimately reports throughput, on-time rate and median
    cycle time together -- and each of those has its own registered definition.
    """
    codes = [metric_code] if isinstance(metric_code, str) else list(metric_code)
    envelope = {
        "metrics": [get(c) for c in codes],
        "filters_applied": filters,
        "data_as_of": db.data_as_of(),
    }
    if n is not None:
        envelope["n_projects"] = n
    return envelope
