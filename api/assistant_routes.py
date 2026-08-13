"""Authenticated write-only endpoint for assistant audit events.

The separately deployed assistant has no database credential. It sends its
trace to this API, which replaces any claimed identity with the verified token
identity before recording the event through the auditor connection.
"""
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from agent import audit
from . import db

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AuditEvent(BaseModel):
    event: dict[str, Any]


@router.post("/audit", status_code=204)
def record_audit(payload: AuditEvent, request: Request):
    event = dict(payload.event)
    event["identity"] = request.state.identity.username
    audit.record(event)


@router.get("/audit")
def read_audit(request: Request, limit: int = Query(50, ge=1, le=200)):
    """Return only the verified caller's traces; identity is never a parameter."""
    rows = db.fetch(
        "SELECT call_id, asked_at, question, intent, resolved_metric, metric_version, "
        "filters, tool_called, rows_returned, duration_ms, abstained, provenance_complete "
        "FROM tr_gov.agent_audit WHERE identity = %s ORDER BY asked_at DESC LIMIT %s",
        [request.state.identity.username, limit], scope="*")
    return {"calls": rows}
