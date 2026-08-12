"""
Transfer & Conversion Intelligence Platform :: the BI layer's only route to data.

The dashboard talks to the analytics API, never to PostgreSQL. That is the whole
architectural point: BI *visualises*, it never recomputes. If this package held a
connection string it would be one "quick fix" away from someone computing a
percentile here, and the platform would be back to two definitions of cycle time
-- the accreted mess the renovation exists to undo.

Every method below is a thin, typed call onto one governed endpoint. None of them
touches a number: responses are handed back whole, provenance envelope and all,
so the browser can render the definition, population, filters and data vintage
beside each panel without this layer knowing what any metric means.

`identity` is threaded through every call, so the caller's entitlements are
resolved by the API and enforced by the row-level policy. The dashboard never
decides what someone may see.

The injectable `client` is what lets tests drive this in-process against the ASGI
app, so the BI layer is covered without standing a server up.
"""
import os

import httpx

DEFAULT_BASE_URL = os.environ.get("TRANSFEROPS_API", "http://127.0.0.1:8000")


class Api:
    def __init__(self, base_url=DEFAULT_BASE_URL, client=None, identity=None,
                 authorization=None):
        self.base_url = base_url
        self.identity = identity
        self.authorization = authorization
        self._client = client or httpx.Client(base_url=base_url, timeout=30.0)

    def _get(self, path, **params):
        headers = {"X-Demo-User": self.identity} if self.identity else {}
        if self.authorization:
            headers["Authorization"] = self.authorization
        clean = {k: v for k, v in params.items() if v is not None}
        r = self._client.get(path, params=clean, headers=headers)
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload=None, **params):
        headers = {"X-Demo-User": self.identity} if self.identity else {}
        if self.authorization:
            headers["Authorization"] = self.authorization
        clean = {k: v for k, v in params.items() if v is not None}
        r = self._client.post(path, params=clean, json=payload or {}, headers=headers)
        r.raise_for_status()
        return r.json()

    def get(self, path, **params):
        """Closed-call compatibility for the governed assistant executor."""
        return self._get(path, **params)

    # ---- service ----------------------------------------------------------
    def health(self):
        return self._get("/health")

    def whoami(self):
        """Who the platform thinks the viewer is, and what they may see."""
        return self._get("/whoami")

    def catalogue(self):
        return self._get("/catalogue")["metrics"]

    # ---- metrics ----------------------------------------------------------
    def cycle_time(self, group_by="fiscal_year", **filters):
        return self._get("/metrics/cycle-time", group_by=group_by, **filters)

    def schedule_drift(self, group_by="transfer_type", **filters):
        return self._get("/metrics/schedule-drift", group_by=group_by, **filters)

    def forecast(self, **filters):
        return self._get("/metrics/forecast", **filters)

    def stage_cycle_time(self):
        return self._get("/metrics/stage-cycle-time")

    def portfolio(self, **filters):
        return self._get("/metrics/portfolio", **filters)

    # ---- unified filter-scoped marts -------------------------------------
    def kpis(self, **filters):
        return self._get("/mart/kpis", **filters)

    def trend(self, **filters):
        return self._get("/mart/trend", **filters)

    def distribution(self, group_by="transfer_type", **filters):
        return self._get("/mart/distribution", group_by=group_by, **filters)

    def accuracy(self, **filters):
        return self._get("/mart/accuracy", **filters)

    def register(self, limit=500, **filters):
        return self._get("/mart/projects", limit=limit, **filters)

    def filter_options(self):
        return self._get("/mart/filter-options")

    # ---- projects ---------------------------------------------------------
    def projects(self, limit=500, **filters):
        return self._get("/projects", limit=limit, **filters)

    def project(self, project_id):
        return self._get(f"/projects/{project_id}")

    # ---- provider-backed AI ----------------------------------------------
    def ai_status(self):
        return self._get("/ai/status")

    def ai_insight(self, filters=None, kind="portfolio_overview", force=False):
        return self._post("/ai/insight", {
            "kind": kind, "filters": filters or {}, "force": force})

    def ai_risk(self, project_ids=None):
        return self._get("/ai/risk", project_id=project_ids)

    def ai_ask(self, question, filters=None):
        return self._post("/ai/ask", {
            "question": question, "filters": filters or {}})

    def ai_email(self, filters=None, audience="steering_committee",
                 cadence="weekly"):
        return self._post("/ai/email-draft", {
            "filters": filters or {}, "audience": audience,
            "cadence": cadence})

    def ai_runs(self, limit=100):
        return self._get("/ai/runs", limit=limit)
