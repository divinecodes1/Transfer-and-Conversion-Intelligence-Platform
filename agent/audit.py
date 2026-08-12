"""
Transfer & Conversion Intelligence Platform :: assistant audit trail.

Every call is recorded with what it resolved to and what it ran, because an answer
nobody can trace is not usable for a management decision -- and because the only
way to know an assistant is behaving is to be able to look at what it actually did.

The writer connects as `transferops_auditor`, which holds INSERT on this one table
and nothing else. That is the point of a separate role: the assistant reads the
metric layer read-only and writes only its own provenance record, so even a fully
compromised assistant cannot alter a metric or reach a project row it was not
entitled to.

If the audit database is unreachable the call is still answered and the record is
kept in memory, with `degraded` set. Losing observability should not take the
service down -- but it should be visible that it happened, rather than silently
producing an answer that no longer has a trail.
"""
import json
import os
from datetime import datetime, timezone

AUDIT_DSN = os.environ.get(
    "TRANSFEROPS_AUDIT_DSN",
    "postgresql://transferops_auditor:auditor@localhost:5432/transferops")

MEMORY = []          # fallback + what /audit serves for the session
DEGRADED = {"reason": None}


def record(entry):
    """Persist one call. Never raises -- audit failure must not fail the answer."""
    entry = {**entry, "asked_at": entry.get("asked_at")
             or datetime.now(timezone.utc).isoformat()}
    MEMORY.append(entry)

    try:
        import psycopg2
        con = psycopg2.connect(AUDIT_DSN)
        try:
            con.autocommit = True
            con.cursor().execute(
                "INSERT INTO tr_gov.agent_audit "
                "(identity, question, intent, resolved_metric, metric_version, "
                " filters, tool_called, rows_returned, duration_ms, abstained, "
                " provenance_complete) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (entry.get("identity"), entry.get("question"), entry.get("intent"),
                 entry.get("resolved_metric"), entry.get("metric_version"),
                 json.dumps(entry.get("filters") or {}), entry.get("tool_called"),
                 entry.get("rows_returned"), entry.get("duration_ms"),
                 entry.get("abstained"), entry.get("provenance_complete")))
        finally:
            con.close()
        DEGRADED["reason"] = None
        entry["persisted"] = True
    except Exception as exc:
        DEGRADED["reason"] = f"{type(exc).__name__}: {exc}"
        entry["persisted"] = False
    return entry


def recent(limit=50):
    return MEMORY[-limit:]


def status():
    return {"persisted": sum(1 for e in MEMORY if e.get("persisted")),
            "in_memory": len(MEMORY),
            "degraded": DEGRADED["reason"]}
