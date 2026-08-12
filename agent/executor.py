"""
Transfer & Conversion Intelligence Platform :: the trusted half of the agent.

The resolver produces intent. This module is what actually touches data, and it is
ordinary code -- no model output reaches it as syntax. It takes a validated
MetricQuery, looks up where that metric is served from the catalogue (so routing
cannot drift from governance), and calls the read-only API.

Every layer of authority is below the model, not inside the prompt:

    resolver (untrusted input) -> MetricQuery (validated) -> executor (trusted)
                                                          -> read-only API
                                                          -> read-only DB session

Saying "the user is a manager" in a question cannot widen access, because access is
resolved from identity before the executor runs and enforced by the API.
"""
from .schema import Aggregation, Intent

AGG_FIELD = {
    Aggregation.MEDIAN: "median",
    Aggregation.P25: "p25",
    Aggregation.P75: "p75",
    Aggregation.P90: "p90",
    Aggregation.COUNT: "n",
}

# Filters the /projects endpoint understands, for LIST questions.
PROJECT_FILTERS = {"status", "portfolio", "transfer_type",
                   "source_site", "target_site", "health"}


class Executor:
    def __init__(self, api):
        self.api = api
        self._catalogue = None

    def catalogue(self):
        if self._catalogue is None:
            self._catalogue = {m["metric_code"]: m for m in self.api.catalogue()}
        return self._catalogue

    def codes(self):
        return set(self.catalogue())

    def execute(self, query):
        """Run a MetricQuery and return (payload, tool_called)."""
        if not query.is_actionable():
            return None, None

        entry = self.catalogue().get(query.metric_code)
        if entry is None or not entry.get("endpoint"):
            return None, None

        if query.intent == Intent.DEFINE:
            return {"definition_only": True}, f"GET /catalogue/{query.metric_code}"

        if query.intent == Intent.LIST:
            return self._list(query)

        endpoint = entry["endpoint"]
        params = dict(query.filters)
        if query.group_by:
            params["group_by"] = query.group_by

        payload = self.api.get(endpoint, **params)
        return payload, f"GET {endpoint}"

    def _list(self, query):
        params = {k: v for k, v in query.filters.items() if k in PROJECT_FILTERS}
        payload = self.api.get("/projects", limit=200, **params)

        # A threshold ("more than 30 days behind") is applied here, over governed
        # values already returned by the API -- never as a predicate the model wrote.
        if query.threshold is not None:
            payload = dict(payload)
            payload["projects"] = [
                p for p in payload["projects"]
                if (p.get("schedule_deviation_days") or 0) > query.threshold
            ]
            payload["total_matching"] = len(payload["projects"])
        return payload, "GET /projects"

    # ---- reading results -------------------------------------------------
    @staticmethod
    def top_of(payload, field, largest=True):
        """Best/worst group in a distribution response, for RANK questions."""
        rows = [r for r in payload.get("series", [])
                if r.get(field) is not None and r.get("group_value") is not None]
        if not rows:
            return None
        return sorted(rows, key=lambda r: r[field], reverse=largest)[0]

    @staticmethod
    def value_of(payload, agg):
        """The headline number when a question asked for one figure."""
        rows = payload.get("series", [])
        if len(rows) == 1:
            return rows[0].get(AGG_FIELD[agg])
        return None
