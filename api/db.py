"""
Transfer & Conversion Intelligence Platform :: read-only warehouse access for the API layer.

Three rules this module exists to enforce:

  * The service connects with a READ-ONLY session. Not "we promise not to write" --
    the database refuses. This is the same posture the AI agent needs (LLM01/LLM06:
    never grant an agent more authority than its task requires), so the API earns
    it first and the agent inherits it.

  * Callers pass VALUES, never SQL. Every filter is a parameterised placeholder and
    every column name is a literal written here in the source. There is no code path
    where a query string reaches the database with user text spliced into it.

  * Connections are POOLED. Each request resolves an identity, reads the
    catalogue and runs a query or three; opening a fresh TCP connection and
    re-authenticating for every one of those turns a handful of cheap reads into
    the dominant cost of the request, and gives a busy service a way to exhaust
    `max_connections` on the warehouse. The pool bounds both.

Every connection handed out is reset to the caller's scope before use, so a
pooled connection can never carry the previous request's entitlements into the
next one -- which is the failure mode that makes pooling worth thinking about
rather than just switching on.
"""
import contextvars
import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pgpool

# The portfolio scope for the request in flight, set by the auth middleware and
# read when a connection is checked out. A context variable rather than a
# parameter on every call because forgetting to thread it through would be a
# silent privilege escalation -- whereas forgetting to *set* it is fail-closed,
# since the RLS policy grants nothing on an empty scope.
CURRENT_SCOPE = contextvars.ContextVar("transferops_scope", default="")

# The API connects as the least-privilege reader created in 10_rls.sql, NOT as the
# schema owner. This is load-bearing rather than tidiness: PostgreSQL superusers
# bypass row-level security unconditionally, so connecting as the bootstrap
# account would leave every entitlement policy installed but inert.
#
# The default is a LOCAL development DSN and nothing else. A deployment supplies
# its own; see docs/PRODUCTION.md and tests/security_checks.py, which asserts no
# non-local host is ever reachable with a committed password.
DSN = os.environ.get("TRANSFEROPS_API_DSN",
                     "postgresql://transferops_reader:reader@localhost:5432/transferops")

# Statement timeout keeps one pathological query from holding the warehouse open;
# the row cap keeps a "show me everything" request from paging the whole portfolio
# into memory. Both matter more once an agent is generating the calls.
STATEMENT_TIMEOUT_MS = int(os.environ.get("TRANSFEROPS_STATEMENT_TIMEOUT_MS", "10000"))
MAX_ROWS = int(os.environ.get("TRANSFEROPS_MAX_ROWS", "5000"))

POOL_MIN = int(os.environ.get("TRANSFEROPS_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("TRANSFEROPS_POOL_MAX", "8"))

_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    """The process-wide connection pool, created on first use."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = pgpool.ThreadedConnectionPool(POOL_MIN, POOL_MAX, DSN)
    return _POOL


def reset_pool():
    """Drop every pooled connection. Used by tests that repoint the DSN."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            try:
                _POOL.closeall()
            finally:
                _POOL = None


@contextmanager
def cursor(scope=None):
    pool_ = _pool()
    con = pool_.getconn()
    bad = False
    try:
        # Read-only is re-asserted per checkout rather than assumed from the last
        # user of this connection.
        con.set_session(readonly=True, autocommit=True)
        cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
        # Row-level security reads this. The caller's entitlements reach the
        # database as a value, so no query anywhere has to remember to filter --
        # and because it is set on every checkout, a recycled connection cannot
        # inherit the previous request's scope.
        cur.execute("SELECT set_config('transferops.portfolios', %s, false)",
                    [scope if scope is not None else CURRENT_SCOPE.get()])
        yield cur
    except psycopg2.Error:
        # A connection that raised may be in an unusable state; discard it rather
        # than returning a broken one to the pool.
        bad = True
        raise
    finally:
        pool_.putconn(con, close=bad)


def fetch(sql, params=None, scope=None):
    """Run a query and return a list of plain dicts."""
    with cursor(scope) as cur:
        cur.execute(sql, params or [])
        return [dict(r) for r in cur.fetchmany(MAX_ROWS)]


def fetch_one(sql, params=None, scope=None):
    rows = fetch(sql, params, scope)
    return rows[0] if rows else None


def where(spec):
    """
    Build a WHERE body from {column_sql: value}, skipping None.

    Keys are SQL fragments written in this repository's own source -- they are never
    taken from a request. Values become placeholders. Returns ("TRUE", []) when no
    filter is active so callers can always interpolate the fragment safely.
    """
    clauses, params = [], []
    for col, val in spec.items():
        if val is None:
            continue
        clauses.append(f"{col} = %s")
        params.append(val)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


# Internal column -> the public parameter name a caller actually used. Echoing
# `completion_fiscal_year` back at someone who asked for `fiscal_year` leaks the
# schema into the contract, and these names are read by humans: they end up in
# dashboard footnotes and in the assistant's statement of scope.
PUBLIC_NAME = {
    "completion_fiscal_year": "fiscal_year",
}


def applied_filters(spec):
    """The non-null filters, echoed back to the caller as part of provenance."""
    out = {}
    for k, v in spec.items():
        if v is None:
            continue
        bare = k.split(".")[-1]
        out[PUBLIC_NAME.get(bare, bare)] = v
    return out


_VINTAGE_TTL = int(os.environ.get("TRANSFEROPS_VINTAGE_TTL", "30"))
_VINTAGE = {"value": None, "at": 0.0}
_VINTAGE_LOCK = threading.Lock()


def data_as_of():
    """
    How current the warehouse is, expressed in the data's own terms rather than
    wall-clock time: the most recent project snapshot we hold. Every metric
    response carries this so a number can always be reproduced against a vintage.

    Cached on a short TTL. It appears in every envelope, so an uncached read is a
    second round trip on every request to report a value that only moves when the
    pipeline runs. The TTL bounds how stale the reported vintage can be, which is
    the property that actually matters -- a vintage that lags reality by a minute
    is fine; one that lags by a deployment is not.
    """
    import time as _time
    now = _time.time()
    with _VINTAGE_LOCK:
        if _VINTAGE["value"] is None or now - _VINTAGE["at"] > _VINTAGE_TTL:
            row = fetch_one(
                "SELECT MAX(snapshot_date) AS d FROM tr_core.fact_project_snapshot",
                scope="*")
            _VINTAGE["value"] = row["d"] if row else None
            _VINTAGE["at"] = now
        return _VINTAGE["value"]
