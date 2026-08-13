"""
Transfer & Conversion Intelligence Platform :: the AI surface of the analytics API.

Six endpoints, and one structural decision that shapes all of them.

**The AI layer reaches data through the governed routes, even in-process.**
`_LocalApi` below maps a path to the very function the HTTP route calls -- not to
a query. So `ai/` still holds no SQL and no connection string, the provenance
envelope is still attached, and the row-level scope is still the one this
request's middleware resolved from the caller's identity. What it avoids is a
service making HTTP calls to itself, which buys a loopback round trip per tool
call and a second place for a timeout to happen.

The route table is closed on purpose, for the same reason the dashboard's is: a
transparent `getattr`-style dispatcher would let a model-chosen string select any
callable in this module. Six entries, written here.

Everything degrades. With no model configured, `/ai/status` says so and the other
endpoints answer 503 with a readable reason -- the dashboards and the
deterministic assistant carry on untouched.
"""
import hashlib
import hmac
import inspect
import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.params import Param
from pydantic import BaseModel, Field
from pydantic_core import PydanticUndefined

from ai import gateway, snapshot as snap, store
from ai.errors import AiError, AiUnavailable

from . import db

router = APIRouter(prefix="/ai", tags=["ai"])

# The HMAC secret for the scheduled refresh endpoint. Unset means the endpoint
# refuses every request rather than defaulting to open -- a cron trigger that
# anyone can fire is a way to spend an AI budget from the outside.
CRON_SECRET = os.environ.get("TRANSFEROPS_AI_CRON_SECRET", "")


class _LocalApi:
    """
    The governed API, called in-process, with the request's own scope.

    Closed route list; every value is a function written in this file's imports.
    Nothing a model emits is ever used to look up a callable.
    """

    # path -> the name of the governed route function that serves it. Names, not
    # references, because this module is imported *by* the one that defines them;
    # they are resolved on first use instead. Still a closed list of literals
    # written here -- nothing a model emits selects a callable.
    ROUTES = {
        "/mart/kpis": "mart_kpis",
        "/mart/trend": "mart_trend",
        "/mart/distribution": "mart_distribution",
        "/mart/accuracy": "mart_accuracy",
        "/mart/projects": "mart_projects",
        "/mart/filter-options": "mart_filter_options",
    }

    def get(self, path, **params):
        name = self.ROUTES.get(path)
        if name is None:
            raise AiError(f"{path} is not a governed route.")
        from . import main as governed
        route = getattr(governed, name)
        clean = {k: v for k, v in params.items() if v is not None}

        # FastAPI replaces Query(...) markers with plain values when a route is
        # entered over HTTP.  This adapter intentionally calls the same route
        # in-process, so omitted parameters need that small piece of dependency
        # resolution here as well; otherwise a Query object can reach the SQL
        # driver's parameter list (for example mart_projects' default offset).
        for parameter in inspect.signature(route).parameters.values():
            marker = parameter.default
            if (parameter.name not in clean and isinstance(marker, Param)
                    and marker.default is not PydanticUndefined):
                clean[parameter.name] = marker.default

        return route(**clean)


def _require_model():
    if not gateway.configured():
        raise HTTPException(
            status_code=503,
            detail="No AI model is configured for this deployment. "
                   "Set TRANSFEROPS_AI_API_KEY (see .env.example).")


def _require_admin(request):
    identity = request.state.identity
    if "PLATFORM_ADMIN" not in identity.roles:
        raise HTTPException(status_code=403,
                            detail="platform administrator required")


def _handle(exc):
    """An AI failure, as an HTTP response the UI can show verbatim."""
    raise HTTPException(status_code=getattr(exc, "status_code", 502),
                        detail=str(exc))


class Filters(BaseModel):
    fiscal_year: int | None = None
    site: str | None = None
    transfer_type: str | None = None
    portfolio: str | None = None
    complexity: str | None = None


class InsightRequest(BaseModel):
    kind: str = "portfolio_overview"
    filters: Filters = Field(default_factory=Filters)
    force: bool = False


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    filters: Filters = Field(default_factory=Filters)


class EmailRequest(BaseModel):
    filters: Filters = Field(default_factory=Filters)
    audience: str = "steering_committee"
    cadence: str = "weekly"


# ---------------------------------------------------------------------------
@router.get("/status")
def ai_status():
    """
    What model this deployment talks to, and whether the cache is healthy.

    Read by the frontend before it renders an AI panel: an empty card with a
    retry button on a deployment that was never given a key is worse than no
    card. It reports the provider and model, never the credential.
    """
    return {"ai": gateway.describe(), "cache": store.status()}


@router.post("/insight")
def ai_insight(body: InsightRequest):
    """
    The cached narrative for a scope, generated when the cache is cold.

    Valid means unexpired *and* written against the current warehouse vintage --
    a briefing describing a previous load is served to nobody, however fresh its
    timestamp. `force` regenerates on demand.
    """
    _require_model()
    from ai import insights

    filters = body.filters.model_dump()
    key = snap.scope_key(body.kind, filters)

    if not body.force:
        cached = store.read_insight(db.fetch, body.kind, key, db.data_as_of())
        if cached:
            return cached

    try:
        return store.save_insight(insights.generate(_LocalApi(), body.kind, filters))
    except AiError as exc:
        _handle(exc)


@router.get("/risk")
def ai_risk(project_id: list[str] | None = Query(None)):
    """
    Delay-risk scores for the caller's entitled projects.

    Never generates on read: putting a model in a dashboard's latency path is how
    a page-load budget becomes a model-provider budget. Scores are written by the
    nightly refresh or by an explicit admin run.
    """
    try:
        rows = store.read_risk(db.fetch, project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"risk store unreachable: {exc}")
    return {
        "data_as_of": db.data_as_of(),
        "note": ("Model estimates, not governed metrics. Not registered in "
                 "tr_gov.metric_definition and never used to compute a KPI."),
        "scores": rows,
    }


@router.post("/ask")
def ai_ask(body: AskRequest):
    """
    Answer a question through the governed metric tools.

    Returns the answer, the trace of every tool call behind it, and the last
    result set -- so a reader can check the working rather than trusting the
    prose.
    """
    _require_model()
    from ai import ask

    try:
        return ask.answer(_LocalApi(), body.question, body.filters.model_dump())
    except AiError as exc:
        _handle(exc)


@router.post("/email-draft")
def ai_email_draft(body: EmailRequest):
    """Draft a report email for one audience. Drafts only -- nothing is sent."""
    _require_model()
    from ai import email

    try:
        return email.draft(_LocalApi(), body.filters.model_dump(),
                           body.audience, body.cadence)
    except AiError as exc:
        _handle(exc)


@router.get("/runs")
def ai_runs(request: Request, limit: int = Query(100, ge=1, le=500)):
    """
    The automation history: every refresh, whether it worked, and what it cost.

    This is what the automation screen reads. A nightly job with no visible run
    history is a job that has been failing for a fortnight.
    """
    _require_admin(request)
    try:
        return {"runs": store.read_runs(db.fetch, limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"run log unreachable: {exc}")


@router.post("/refresh")
async def ai_refresh(request: Request, job: str = Query("all")):
    """
    The scheduled refresh trigger, signature-verified.

    Called by cron, the DAG, or an admin. The signature is over the raw body with
    a shared secret, compared in constant time; with no secret configured the
    endpoint refuses everything rather than defaulting to open. That matters more
    here than on a read endpoint -- this one spends money.
    """
    _require_model()
    from ai import refresh

    if not CRON_SECRET:
        raise HTTPException(
            status_code=503,
            detail="TRANSFEROPS_AI_CRON_SECRET is not set; the refresh endpoint "
                   "is disabled rather than open.")

    signature = request.headers.get("x-transferops-signature", "")
    body = await request.body()
    expected = hmac.new(CRON_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="bad or missing signature")

    api = _LocalApi()
    trigger = request.headers.get("x-transferops-trigger", "cron")
    try:
        if job == "insights":
            return refresh.refresh_insights(api, trigger)
        if job == "risk":
            return refresh.refresh_risk(api, trigger)
        return refresh.run_all(api, trigger)
    except AiUnavailable as exc:
        _handle(exc)
    except AiError as exc:
        _handle(exc)
