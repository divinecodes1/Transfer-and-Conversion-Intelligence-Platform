"""
Transfer & Conversion Intelligence Platform :: turning a governed result into an answer that can be checked.

The measure of this agent is not whether the prose reads well. It is whether the
metric, population, filters and number are right, and whether a reader can
reproduce them in the dashboard. So every answer carries:

    what the question was interpreted to mean
    which registered metric was used, and its version
    the population that metric covers
    the filters actually applied
    how fresh the data is
    which tool was called

An answer that cannot show those is a claim, not a result -- and the abstention
paths below are deliberately as first-class as the success paths.
"""
from .schema import Aggregation, Intent


def _fmt(value, unit="days"):
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value * 100:.0f}%"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.0f} days"


# Not every governed source is a percentile distribution. The portfolio mart
# reports counts and ratios directly, and the stage view is keyed by a stage pair
# rather than a single grouping column, so the reader adapts rather than the SQL.
DIRECT_VALUE = {
    "TRANSFER_THROUGHPUT": ("throughput", "sum"),
    "ON_TIME_COMPLETION_RATE": ("on_time_rate", "weighted"),
}


def _label(row):
    """A human label for a series row, whatever shape the source has."""
    if row.get("group_value") not in (None, "ALL"):
        return str(row["group_value"])
    if row.get("from_stage"):
        return f"{row['from_stage']} → {row['to_stage']}"
    if row.get("fiscal_year") is not None:
        return f"FY{row['fiscal_year']}" + (
            f" {row['portfolio']}" if row.get("portfolio") else "")
    return "all projects"


def _scope(query, payload):
    filters = (payload or {}).get("filters_applied") or query.filters or {}
    if not filters:
        return "the whole portfolio"
    return ", ".join(f"{k.split('.')[-1].replace('_', ' ')} = {v}"
                     for k, v in filters.items())


def build(query, payload, tool, catalogue):
    """Compose the answer envelope returned by POST /ask."""
    base = {
        "question": query.question,
        "intent": query.intent.value,
        "interpretation": None,
        "answer": None,
        "metric": None,
        "filters_applied": (payload or {}).get("filters_applied", query.filters),
        "data_as_of": (payload or {}).get("data_as_of"),
        "tool_called": tool,
        "provenance_complete": False,
    }

    # ---- abstentions ------------------------------------------------------
    if query.intent == Intent.CLARIFY:
        options = [{"metric_code": c,
                    "business_name": catalogue[c]["business_name"],
                    "definition": catalogue[c]["definition"]}
                   for c in query.candidates if c in catalogue]
        base["answer"] = (
            f"{query.reason} Which do you mean?\n" +
            "\n".join(f"  · {o['business_name']} — {o['definition']}" for o in options))
        base["options"] = options
        base["provenance_complete"] = True
        return base

    if query.intent == Intent.REFUSE:
        base["answer"] = query.reason
        # A question outside the metric catalogue may still be a question the
        # *platform documentation* can answer ("what is a fiscal year here?").
        # Offering that is help; answering it with a number would not be.
        if query.sources:
            base["answer"] += (
                "\n\nI can't compute that, but these may help:\n" +
                "\n".join(f"  · {s['title']}: {s['text'][:150]}…"
                          for s in query.sources))
            base["sources"] = query.sources
        base["provenance_complete"] = True
        return base

    metric = catalogue.get(query.metric_code)
    if metric is None:
        base["intent"] = Intent.REFUSE.value
        base["answer"] = "That metric is not registered in the catalogue."
        base["provenance_complete"] = True
        return base

    base["metric"] = {
        "metric_code": metric["metric_code"],
        "business_name": metric["business_name"],
        "definition": metric["definition"],
        "population": metric["population"],
        "exclusions": metric["exclusions"],
        "version": metric["version"],
        "owner": metric["owner"],
    }
    unit = metric.get("unit", "days")

    # ---- definition -------------------------------------------------------
    if query.intent == Intent.DEFINE:
        base["interpretation"] = f"Definition of {metric['business_name']}."
        base["answer"] = (
            f"{metric['business_name']} (v{metric['version']}) is "
            f"`{metric['definition']}`, at {metric['grain']} grain, measured in "
            f"{unit}. Population: {metric['population']}. "
            f"Excludes: {metric['exclusions']}. Owned by {metric['owner']}.")
        # The authoritative answer above comes from the catalogue. Retrieved
        # documents are attached as *supporting context* and are never allowed to
        # restate the definition -- a definition sourced from a document would be
        # a second source of truth, which is the failure this platform prevents.
        if query.sources:
            base["sources"] = query.sources
        base["provenance_complete"] = True
        return base

    if payload is None:
        base["intent"] = Intent.REFUSE.value
        base["answer"] = (f"{metric['business_name']} is registered but is not "
                          f"served by an endpoint, so I cannot compute it.")
        return base

    # ---- list -------------------------------------------------------------
    if query.intent == Intent.LIST:
        projects = payload.get("projects", [])
        base["interpretation"] = (
            f"Open projects" +
            (f" more than {query.threshold} days past baseline" if query.threshold else "") +
            f", scoped to {_scope(query, payload)}.")
        base["answer"] = f"{len(projects)} projects match."
        base["rows"] = [
            {"project_id": p["project_id"], "transfer_type": p["transfer_type"],
             "portfolio": p["portfolio"], "health": p["health"],
             "schedule_deviation_days": p["schedule_deviation_days"]}
            for p in projects[:25]]
        base["n_projects"] = payload.get("total_matching", len(projects))
        base["provenance_complete"] = base["data_as_of"] is not None
        return base

    series = payload.get("series", [])
    base["n_projects"] = payload.get("n_projects")

    # ---- metrics served as direct values, not distributions ---------------
    if query.metric_code in DIRECT_VALUE:
        field, how = DIRECT_VALUE[query.metric_code]
        rows = [r for r in series if r.get(field) is not None]
        base["interpretation"] = (f"{metric['business_name']}, scoped to "
                                  f"{_scope(query, payload)}.")
        base["rows"] = rows
        if not rows:
            base["answer"] = "No rows matched that scope."
            return base
        if how == "sum":
            total = sum(r[field] for r in rows)
            base["answer"] = (f"{metric['business_name']}: {_fmt(total, 'count')} "
                              f"across {len(rows)} fiscal-period groups.")
        else:
            # Weighted by throughput -- averaging the ratios would let a
            # three-project period count as much as a fifty-project one.
            weight = sum(r.get("throughput") or 0 for r in rows) or len(rows)
            value = sum((r[field] or 0) * (r.get("throughput") or 1)
                        for r in rows) / weight
            base["answer"] = (f"{metric['business_name']}: {_fmt(value, 'ratio')} "
                              f"across {weight:,.0f} completed projects.")
        base["provenance_complete"] = True
        return base

    field = {Aggregation.MEDIAN: "median", Aggregation.P25: "p25",
             Aggregation.P75: "p75", Aggregation.P90: "p90",
             Aggregation.COUNT: "n"}[query.aggregation]
    rows = [r for r in series if r.get(field) is not None]

    # ---- rank -------------------------------------------------------------
    if query.intent == Intent.RANK:
        if not rows:
            base["answer"] = "No rows matched that scope."
            return base
        ranked = sorted(rows, key=lambda r: r[field], reverse=True)
        top, bottom = ranked[0], ranked[-1]
        base["interpretation"] = (
            f"{metric['business_name']} ({query.aggregation.value}) by "
            f"{query.group_by}, ranked, scoped to {_scope(query, payload)}.")
        base["answer"] = (
            f"{_label(top)} has the highest {query.aggregation.value} "
            f"{metric['business_name'].lower()} at {_fmt(top[field], unit)} "
            f"(n={top.get('n')}). Lowest is {_label(bottom)} at "
            f"{_fmt(bottom[field], unit)}.")
        base["rows"] = ranked
        base["provenance_complete"] = True
        return base

    # ---- compare ----------------------------------------------------------
    if query.intent == Intent.COMPARE:
        rows.sort(key=_label)
        if len(rows) < 2:
            base["answer"] = "Not enough groups in scope to compare."
            base["rows"] = rows
            return base
        a, b = rows[0], rows[-1]
        delta = b[field] - a[field]
        base["interpretation"] = (
            f"{metric['business_name']} ({query.aggregation.value}) across "
            f"{query.group_by}, scoped to {_scope(query, payload)}.")
        base["answer"] = (
            f"{metric['business_name']} moved from {_fmt(a[field], unit)} "
            f"({_label(a)}, n={a.get('n')}) to {_fmt(b[field], unit)} "
            f"({_label(b)}, n={b.get('n')}) — a change of {delta:+,.0f} {unit}.")
        base["rows"] = rows
        base["provenance_complete"] = True
        return base

    # ---- retrieve ---------------------------------------------------------
    base["interpretation"] = (
        f"{metric['business_name']} ({query.aggregation.value})"
        + (f" by {query.group_by}" if query.group_by else "")
        + f", scoped to {_scope(query, payload)}.")
    if not rows:
        base["answer"] = "No rows matched that scope."
    elif len(rows) == 1:
        base["answer"] = (f"{metric['business_name']} "
                          f"({query.aggregation.value}) is "
                          f"{_fmt(rows[0][field], unit)} across "
                          f"{rows[0].get('n')} projects.")
    else:
        parts = [f"{_label(r)}: {_fmt(r[field], unit)}" for r in rows]
        base["answer"] = (f"{metric['business_name']} "
                          f"({query.aggregation.value}) — " + "; ".join(parts))
    base["rows"] = rows
    base["provenance_complete"] = True
    return base
