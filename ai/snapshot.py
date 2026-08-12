"""
Transfer & Conversion Intelligence Platform :: the grounding layer.

Every prompt in this package is grounded in a snapshot produced here, and this
module gets its numbers exactly one way: by calling the governed API, under a
resolved identity, through the same endpoints the dashboards call. There is no
database handle in `ai/` at all.

That is the whole safety argument, and it is structural rather than a promise:

  * **The model cannot see a project it may not see.** The snapshot is fetched
    with the caller's identity, so the row-level policy filters it before it is
    ever serialised into a prompt. A narrative cannot mention a portfolio the
    reader is not entitled to, because the narrative was written from numbers
    that excluded it.

  * **The model cannot invent a figure and have it believed.** Everything it is
    shown carries its provenance envelope -- definition, population, filters,
    vintage -- and the reply is rendered next to the same envelope. A number in
    the prose that is not in the snapshot is visibly not from the platform.

  * **The model cannot widen its own scope.** It never issues a query; this
    module does, from a filter object the caller supplied.

`tests/ai_checks.py` asserts the first of those by driving the snapshot as two
different users and checking the payloads differ.
"""
import json

# The filter contract, shared by every AI surface and identical to the one the
# dashboards use. Named here so a prompt and a chart can never disagree about
# what "this scope" meant.
FILTER_KEYS = ("fiscal_year", "site", "transfer_type", "portfolio", "complexity")

# How many of the worst projects to name. Enough for a briefing to be specific
# about where the risk is, small enough that the prompt stays cheap and the model
# does not start summarising a table instead of reading it.
WORST_N = 10


def clean(filters):
    """Just the recognised, non-null filters -- in a fixed key order."""
    filters = filters or {}
    return {k: filters[k] for k in FILTER_KEYS
            if filters.get(k) not in (None, "")}


def scope_key(kind, filters):
    """
    The cache key for one narrative scope.

    Order-independent and null-normalised, so the same scope reached from two
    screens is one cache entry rather than two -- and, more importantly, so a
    briefing written for FY26/PF_AUTO can never be served for a different scope.
    That failure mode makes a cached AI summary actively misleading rather than
    merely stale.
    """
    filters = clean(filters)
    parts = [kind] + [f"{k}={filters.get(k, 'all')}" for k in FILTER_KEYS]
    return "|".join(str(p) for p in parts)


def _rows(payload, key="series"):
    if not isinstance(payload, dict):
        return []
    return payload.get(key) or []


def build(api, filters=None, *, worst=WORST_N):
    """
    The governed metric snapshot for one filter scope.

    `api` is any object with `.get(path, **params)` -- the BI client, the
    assistant's client, or a test double driving the ASGI app in-process. The
    same seam that lets the assistant be tested without a server lets the AI
    layer be tested without a model.
    """
    f = clean(filters)
    kpis = api.get("/mart/kpis", **f)
    trend = api.get("/mart/trend", **{k: v for k, v in f.items()
                                      if k != "fiscal_year"})
    distribution = api.get("/mart/distribution", group_by="transfer_type", **f)
    accuracy = api.get("/mart/accuracy", **{k: v for k, v in f.items()
                                            if k != "fiscal_year"})
    register = api.get("/mart/projects", sort_by="schedule_deviation_days",
                       descending=True, limit=worst, **f)

    projects = register.get("projects") or []
    return {
        "filters": f,
        "data_as_of": str(kpis.get("data_as_of") or ""),
        "kpis": kpis.get("kpis") or {},
        "definitions": kpis.get("metrics") or [],
        "trend": _rows(trend),
        "distribution_by_transfer_type": _rows(distribution),
        "forecast_accuracy_by_horizon": _rows(accuracy),
        "worst_projects": [_compact(p) for p in projects[:worst]],
        "project_count": register.get("total_matching", len(projects)),
    }


# The columns a narrative is allowed to reason about. An allowlist rather than
# the whole row: a register row carries fields that add nothing to a briefing and
# every one of them is prompt budget spent, and repeated nightly.
NARRATIVE_COLUMNS = (
    "project_id", "project_name", "status", "transfer_type", "complexity_class",
    "portfolio", "source_site", "target_site", "health",
    "schedule_deviation_days", "completion_variance_days",
    "actual_cycle_time_days", "wip_age_days", "revision_count", "was_replanned",
    "baseline_finish", "latest_finish",
)


def _compact(project):
    return {k: _plain(project.get(k)) for k in NARRATIVE_COLUMNS
            if project.get(k) is not None}


def _plain(value):
    """Dates and decimals to something json.dumps will accept."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def serialise(snapshot, limit=24000):
    """
    The snapshot as prompt text.

    Truncated rather than unbounded: a portfolio that grows tenfold should make
    the briefing less detailed, not make every nightly refresh fail on a context
    limit at 05:15 with nobody watching.
    """
    text = json.dumps(snapshot, default=_plain, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "  …(truncated)"


def describe_scope(filters):
    """The filter scope in words, for a prompt and for a report subject line."""
    f = clean(filters)
    if not f:
        return "the whole transfer portfolio"
    return ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in f.items())
