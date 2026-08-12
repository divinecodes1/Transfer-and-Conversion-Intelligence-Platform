"""
Transfer & Conversion Intelligence Platform :: the tr_ai cache.

Writes go through `transferops_ai`, a role that holds INSERT/UPDATE on three
tables in `tr_ai` and nothing anywhere else -- no SELECT in `tr_core`, no SELECT
in `tr_metric`. That is the same argument the audit writer makes, applied to the
generator: a fully compromised AI layer can write a bad narrative, and it still
cannot read a project row or alter a metric. The numbers it writes *about* came
in through the governed API under the caller's identity, never from here.

Reads are the API's job and go through `transferops_reader`, so they are
row-level scoped like every other read in the platform.

Cache behaviour worth being explicit about:

  * **A narrative expires on time OR on vintage.** The 24-hour TTL bounds how
    stale a briefing can get; the stored `data_as_of` makes a briefing written
    against an older warehouse load invalid the moment a new one lands. The
    second condition is the one that matters -- a briefing that is four hours old
    and describes last week's data is the worse failure.

  * **Nothing here is fatal.** Every function degrades to a no-op with a reason
    if `tr_ai` is unreachable. An unavailable cache should cost a little money in
    regenerated narratives, not take the AI surfaces down.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

AI_DSN = os.environ.get(
    "TRANSFEROPS_AI_DSN",
    "postgresql://transferops_ai:ai@localhost:5432/transferops")

TTL_HOURS = int(os.environ.get("TRANSFEROPS_AI_TTL_HOURS", "24"))

DEGRADED = {"reason": None}
_LOCK = threading.Lock()


def _connect():
    import psycopg2
    con = psycopg2.connect(AI_DSN)
    con.autocommit = True
    return con


def _write(sql, params, returning=False):
    """Run one write. Never raises -- a cache failure is not an outage."""
    try:
        con = _connect()
        try:
            cur = con.cursor()
            cur.execute(sql, params)
            value = cur.fetchone()[0] if returning else True
        finally:
            con.close()
        with _LOCK:
            DEGRADED["reason"] = None
        return value
    except Exception as exc:  # noqa: BLE001 -- degradation, not failure
        with _LOCK:
            DEGRADED["reason"] = f"{type(exc).__name__}: {exc}"
        return None


def status():
    with _LOCK:
        return {"degraded": DEGRADED["reason"], "ttl_hours": TTL_HOURS}


# ---- Narratives ------------------------------------------------------------
def save_insight(record, ttl_hours=None):
    """Cache one narrative against the vintage it describes."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours or TTL_HOURS)
    ok = _write(
        """
        INSERT INTO tr_ai.insight
            (kind, scope_key, portfolio, filters, headline, content, highlights,
             model, provider, data_as_of, generated_at, expires_at)
        VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
        ON CONFLICT (kind, scope_key) DO UPDATE SET
            portfolio    = EXCLUDED.portfolio,
            filters      = EXCLUDED.filters,
            headline     = EXCLUDED.headline,
            content      = EXCLUDED.content,
            highlights   = EXCLUDED.highlights,
            model        = EXCLUDED.model,
            provider     = EXCLUDED.provider,
            data_as_of   = EXCLUDED.data_as_of,
            generated_at = EXCLUDED.generated_at,
            expires_at   = EXCLUDED.expires_at
        """,
        [record["kind"], record["scope_key"], record.get("portfolio"),
         json.dumps(record.get("filters") or {}), record.get("headline"),
         record["content"], json.dumps(record.get("highlights") or []),
         record.get("model"), record.get("provider"),
         record.get("data_as_of") or None, now, expires],
    )
    return {**record, "generated_at": now.isoformat(),
            "expires_at": expires.isoformat(), "cached": False,
            "persisted": bool(ok)}


def read_insight(fetch, kind, scope_key, data_as_of=None):
    """
    The cached narrative for a scope, if it is still valid.

    `fetch` is the API's read-only, entitlement-scoped query function -- this
    module does not read with its own role, so a cached narrative is subject to
    the same row-level policy as the numbers it describes.

    Valid means unexpired *and* written against the current warehouse vintage.
    Serving a briefing that describes a load two refreshes ago, beside charts
    that do not, is worse than showing nothing and regenerating.
    """
    rows = fetch(
        "SELECT kind, scope_key, filters, headline, content, highlights, model, "
        "       provider, data_as_of, generated_at, expires_at "
        "FROM tr_ai.insight "
        "WHERE kind = %s AND scope_key = %s AND expires_at > now()",
        [kind, scope_key])
    if not rows:
        return None
    row = rows[0]
    if data_as_of and row.get("data_as_of") and str(row["data_as_of"]) != str(data_as_of):
        return None
    return {**row, "cached": True}


# ---- Risk scores -----------------------------------------------------------
def save_risk(rows, data_as_of=None):
    """Upsert a batch of scores. Returns how many were stored."""
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    stored = 0
    for row in rows:
        if row.get("project_key") is None:
            continue
        ok = _write(
            """
            INSERT INTO tr_ai.project_risk
                (project_key, risk_score, risk_band, predicted_slip_days,
                 drivers, rationale, model, provider, data_as_of, generated_at)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
            ON CONFLICT (project_key) DO UPDATE SET
                risk_score          = EXCLUDED.risk_score,
                risk_band           = EXCLUDED.risk_band,
                predicted_slip_days = EXCLUDED.predicted_slip_days,
                drivers             = EXCLUDED.drivers,
                rationale           = EXCLUDED.rationale,
                model               = EXCLUDED.model,
                provider            = EXCLUDED.provider,
                data_as_of          = EXCLUDED.data_as_of,
                generated_at        = EXCLUDED.generated_at
            """,
            [row["project_key"], row["risk_score"], row["risk_band"],
             row.get("predicted_slip_days"), json.dumps(row.get("drivers") or []),
             row.get("rationale"), row.get("model"), row.get("provider"),
             data_as_of or None, now],
        )
        stored += bool(ok)
    return stored


def read_risk(fetch, project_ids=None):
    """
    Scores for the caller's entitled scope.

    Joined through `tr_core.dim_project` rather than read straight from
    `tr_ai.project_risk`: that join is what puts the scores inside the row-level
    policy, so a score can never name a project its reader could not otherwise
    see. Never generates on read -- scoring on a page load would put a model in
    the latency path of a dashboard.
    """
    sql = ("SELECT p.project_id, p.project_name, r.risk_score, r.risk_band, "
           "       r.predicted_slip_days, r.drivers, r.rationale, r.model, "
           "       r.provider, r.data_as_of, r.generated_at "
           "FROM tr_ai.project_risk r "
           "JOIN tr_core.dim_project p USING (project_key) ")
    params = []
    if project_ids:
        sql += "WHERE p.project_id = ANY(%s) "
        params.append(list(project_ids))
    return fetch(sql + "ORDER BY r.risk_score DESC", params)


# ---- Run history -----------------------------------------------------------
def start_run(job, trigger="manual", model=None, provider=None):
    """Open a run row. Returns its id, or None when the cache is unreachable."""
    return _write(
        "INSERT INTO tr_ai.run_log (job, status, trigger, model, provider, "
        "started_at) VALUES (%s,'running',%s,%s,%s, now()) RETURNING run_id",
        [job, trigger, model, provider], returning=True)


def finish_run(run_id, status, *, item_count=0, scopes=None, detail=None,
               error_message=None):
    """Close a run row with its outcome. A missing id is a no-op, not an error."""
    if run_id is None:
        return False
    return bool(_write(
        "UPDATE tr_ai.run_log SET status = %s, item_count = %s, scopes = %s::jsonb, "
        "       detail = %s, error_message = %s, finished_at = now(), "
        "       duration_ms = CAST(EXTRACT(EPOCH FROM (now() - started_at)) * 1000 AS INTEGER) "
        "WHERE run_id = %s",
        [status, item_count, json.dumps(scopes or []), detail,
         (error_message or None), run_id]))


def read_runs(fetch, limit=100):
    """The automation history, newest first."""
    return fetch(
        "SELECT run_id, job, status, trigger, item_count, scopes, detail, "
        "       error_message, model, provider, started_at, finished_at, duration_ms "
        "FROM tr_ai.run_log ORDER BY started_at DESC LIMIT %s", [limit])
