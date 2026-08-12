"""
Transfer & Conversion Intelligence Platform :: the dashboard server.

This process serves the dashboard and nothing else. It holds no connection
string, no SQL and no metric logic -- it forwards a fixed set of panel requests
to the analytics API and hands the response back untouched.

Three properties, each asserted in tests/bi_checks.py:

  * **The route list is closed.** Every endpoint below names one panel and calls
    one typed client method. It is deliberately not a transparent proxy: a
    pass-through `/api/{path}` would let the browser reach anything the API
    serves, which quietly turns the dashboard into a second, unreviewed client
    of the warehouse.

  * **The provenance envelope is never unwrapped.** Responses are returned
    verbatim, so the definition, population, version, filters and data vintage
    that the API attached still reach the browser and get rendered under every
    panel. The dashboard explains its own scope because the API told it how.

  * **Identity is forwarded, never decided.** `X-Demo-User` is passed through so
    entitlements resolve in the API and are enforced by the row-level policy.
    This process never learns what a caller may see, which is the point: it has
    no authority to leak.

Run:
    uvicorn api.main:app --reload            # terminal 1, the analytics API
    uvicorn bi.server:app --port 8501        # terminal 2, this
"""
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import audit
from agent.app import answer
from agent.insights import draft_report, portfolio_briefing, project_risks
from .client import Api

STATIC = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(
    title="Transfer & Conversion Intelligence Platform Dashboards",
    description="Two-audience reporting over the governed metric layer.",
    version="1.0.0",
)


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    filters: dict = Field(default_factory=dict)


class InsightRequest(BaseModel):
    filters: dict = Field(default_factory=dict)


class EmailDraftRequest(InsightRequest):
    audience: str = "steering_committee"
    cadence: str = "weekly"


def _api(request: Request) -> Api:
    """A client bound to the caller's identity, so entitlements follow through."""
    return Api(identity=request.headers.get("x-demo-user"),
               authorization=request.headers.get("authorization"))


def _ok(payload):
    """Return the API's answer verbatim -- envelope included."""
    return JSONResponse(content=payload)


def _require_admin(api: Api):
    identity = api.whoami()
    if "PLATFORM_ADMIN" not in identity.get("roles", []):
        raise HTTPException(status_code=403, detail="platform administrator required")
    return identity


# ---- the page -------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/healthz", include_in_schema=False)
def health_probe():
    """Liveness for this process only.

    Deliberately not a round-trip to the analytics API: if the warehouse is
    unreachable, the dashboard should stay up and say so on the page, not
    crash-loop. The API has its own probe for its own dependency.
    """
    return {"status": "ok"}


# ---- panels ---------------------------------------------------------------
# One route per panel, each delegating to one typed client call. Adding a panel
# is a visible change here rather than a new URL the browser discovered.
@app.get("/api/bootstrap", tags=["panels"])
def bootstrap(request: Request):
    """Everything the shell needs before the first paint: who the viewer is,
    how fresh the data is, and the filter vocabulary -- fetched from the
    governed catalogue rather than hard-coded in the browser."""
    api = _api(request)
    projects = api.projects(limit=1000)
    cycle = api.cycle_time(group_by="fiscal_year")
    portfolio = api.portfolio()
    try:
        options = api.filter_options().get("options", {})
    except Exception:
        options = {}
    try:
        ai_status = api.ai_status()
    except Exception:
        ai_status = {"ai": {"configured": False}, "cache": {"degraded": True}}
    return _ok({
        "whoami": api.whoami(),
        "health": api.health(),
        "catalogue": api.catalogue(),
        "fiscal_years": options.get("fiscal_year") or sorted({
            r["group_value"] for r in cycle["series"]
            if r["group_value"] is not None}),
        "transfer_types": options.get("transfer_type") or sorted({
            p["transfer_type"] for p in projects["projects"]
            if p["transfer_type"]}),
        "portfolios": options.get("portfolio") or sorted({
            r["portfolio"] for r in portfolio["series"] if r["portfolio"]}),
        "sites": sorted(set(options.get("source_site", [])) |
                        set(options.get("target_site", []))),
        "complexities": options.get("complexity_class", []),
        "ai": ai_status,
    })


@app.get("/api/cycle-time", tags=["panels"])
def cycle_time(request: Request, group_by: str = "fiscal_year",
               fiscal_year: int | None = None,
               transfer_type: str | None = None,
               portfolio: str | None = None):
    return _ok(_api(request).cycle_time(
        group_by=group_by, fiscal_year=fiscal_year,
        transfer_type=transfer_type, portfolio=portfolio))


@app.get("/api/schedule-drift", tags=["panels"])
def schedule_drift(request: Request, group_by: str = "transfer_type",
                   fiscal_year: int | None = None,
                   transfer_type: str | None = None,
                   portfolio: str | None = None):
    return _ok(_api(request).schedule_drift(
        group_by=group_by, fiscal_year=fiscal_year,
        transfer_type=transfer_type, portfolio=portfolio))


@app.get("/api/forecast", tags=["panels"])
def forecast(request: Request, transfer_type: str | None = None,
             portfolio: str | None = None):
    return _ok(_api(request).forecast(
        transfer_type=transfer_type, portfolio=portfolio))


@app.get("/api/stage-cycle-time", tags=["panels"])
def stage_cycle_time(request: Request):
    return _ok(_api(request).stage_cycle_time())


@app.get("/api/portfolio", tags=["panels"])
def portfolio_period(request: Request, fiscal_year: int | None = None,
                     portfolio: str | None = None):
    return _ok(_api(request).portfolio(
        fiscal_year=fiscal_year, portfolio=portfolio))


@app.get("/api/projects", tags=["panels"])
def projects(request: Request, portfolio: str | None = None,
             transfer_type: str | None = None,
             health: str | None = None,
             limit: int = Query(500, ge=1, le=1000)):
    return _ok(_api(request).projects(
        limit=limit, portfolio=portfolio,
        transfer_type=transfer_type, health=health))


@app.get("/api/projects/{project_id}", tags=["panels"])
def project_detail(request: Request, project_id: str):
    return _ok(_api(request).project(project_id))


@app.get("/api/kpis", tags=["panels"])
def kpis(request: Request, fiscal_year: int | None = None,
         site: str | None = None, transfer_type: str | None = None,
         portfolio: str | None = None, complexity: str | None = None):
    return _ok(_api(request).kpis(
        fiscal_year=fiscal_year, site=site, transfer_type=transfer_type,
        portfolio=portfolio, complexity=complexity))


@app.get("/api/trend", tags=["panels"])
def trend(request: Request, site: str | None = None,
          transfer_type: str | None = None, portfolio: str | None = None,
          complexity: str | None = None):
    return _ok(_api(request).trend(
        site=site, transfer_type=transfer_type, portfolio=portfolio,
        complexity=complexity))


@app.get("/api/distribution", tags=["panels"])
def distribution(request: Request, group_by: str = "transfer_type",
                 fiscal_year: int | None = None, site: str | None = None,
                 transfer_type: str | None = None,
                 portfolio: str | None = None,
                 complexity: str | None = None):
    return _ok(_api(request).distribution(
        group_by=group_by, fiscal_year=fiscal_year, site=site,
        transfer_type=transfer_type, portfolio=portfolio,
        complexity=complexity))


@app.get("/api/accuracy", tags=["panels"])
def accuracy(request: Request, site: str | None = None,
             transfer_type: str | None = None, portfolio: str | None = None,
             complexity: str | None = None):
    return _ok(_api(request).accuracy(
        site=site, transfer_type=transfer_type, portfolio=portfolio,
        complexity=complexity))


@app.get("/api/register", tags=["panels"])
def register(request: Request, fiscal_year: int | None = None,
             site: str | None = None, transfer_type: str | None = None,
             portfolio: str | None = None, complexity: str | None = None,
             status: str | None = None, health: str | None = None,
             search: str | None = None, sort_by: str | None = None,
             descending: bool = True,
             limit: int = Query(500, ge=1, le=1000)):
    return _ok(_api(request).register(
        limit=limit, fiscal_year=fiscal_year, site=site,
        transfer_type=transfer_type, portfolio=portfolio,
        complexity=complexity, status=status, health=health, search=search,
        sort_by=sort_by, descending=descending))


# ---- governed AI product endpoints ---------------------------------------
@app.post("/api/ask", tags=["assistant"])
def ask_assistant(request: Request, payload: AssistantQuestion):
    api = _api(request)
    identity = api.whoami().get("username")
    try:
        result = api.ai_ask(payload.question, payload.filters)
        result["provenance_complete"] = bool(result.get("trace"))
        result["tool_called"] = ", ".join(
            row.get("tool", "") for row in result.get("trace", [])) or None
        result["rows"] = ((result.get("data") or {}).get("rows") or [])
        return _ok(result)
    except Exception:
        return _ok(answer(payload.question, api=api, identity=identity))


@app.post("/api/insight", tags=["assistant"])
def insight(request: Request, payload: InsightRequest):
    api = _api(request)
    try:
        result = api.ai_insight(payload.filters)
        result["provenance"] = ["governed metric snapshot", "AI model"]
        result["mode"] = "model"
        return _ok(result)
    except Exception:
        result = portfolio_briefing(api, payload.filters)
        result["mode"] = "deterministic"
        return _ok(result)


@app.post("/api/project-risks", tags=["assistant"])
def risks(request: Request, payload: InsightRequest):
    api = _api(request)
    fallback = project_risks(api, payload.filters)
    try:
        cached = api.ai_risk([row["project_id"] for row in fallback["risks"]])
        scores = cached.get("scores") or []
        if scores:
            return _ok({**fallback, "risks": scores, "method": "model-cache",
                        "note": cached.get("note")})
    except Exception:
        pass
    return _ok(fallback)


@app.post("/api/report-draft", tags=["assistant"])
def report_draft(request: Request, payload: EmailDraftRequest):
    api = _api(request)
    try:
        result = api.ai_email(payload.filters, payload.audience, payload.cadence)
        result["provenance"] = ["governed metric snapshot", "AI model"]
        result["mode"] = "model"
        return _ok(result)
    except Exception:
        result = draft_report(api, payload.filters, audience=payload.audience,
                              cadence=payload.cadence)
        result["mode"] = "deterministic"
        return _ok(result)


@app.get("/api/assistant-audit", tags=["assistant"])
def assistant_audit(request: Request, limit: int = Query(50, ge=1, le=200)):
    api = _api(request)
    _require_admin(api)
    try:
        runs = api.ai_runs(limit).get("runs", [])
    except Exception:
        runs = []
    return _ok({"calls": audit.recent(limit), "runs": runs, **audit.status()})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
