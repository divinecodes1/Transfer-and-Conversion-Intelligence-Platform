"""
Transfer & Conversion Intelligence Platform :: the knowledge base, generated from the platform itself.

The important design decision: **the metric documents are not written by hand.**
They are generated from `tr_gov.metric_definition`, so a retrieved explanation
cannot contradict the metric it explains. A hand-written glossary is just a
fourth place for a definition to drift -- exactly the failure the catalogue was
built to end, reappearing as documentation.

Four collections, from the spec:

    metric_definitions   generated from the catalogue
    dashboard_metadata   what each panel shows and which metric it uses
    architecture_docs    why the layers exist, curated
    user_guides          fiscal rules, filters, how to read a box plot

Only the last two are hand-written, and neither contains a number.
"""

# ---- curated: explain the platform, never restate a metric -----------------
ARCHITECTURE_DOCS = [
    ("layers",
     "Transfer & Conversion Intelligence Platform separates source data, calculation and presentation. Sources land "
     "in tr_raw exactly as delivered, are typed and deduplicated in tr_stg, become "
     "canonical in tr_core, are calculated once in tr_metric, and are shaped for "
     "reporting in tr_mart. Dashboards and the assistant read the metric layer; "
     "neither recomputes a metric."),
    ("history",
     "Schedule history is preserved explicitly. fact_schedule_revision holds an "
     "immutable baseline plus every replan, and fact_project_snapshot holds the "
     "forecast as it was known on each date. Without these, comparing the original "
     "schedule to the latest one is impossible because the past would be overwritten."),
    ("governance",
     "Every KPI is registered in tr_gov.metric_definition with a definition, grain, "
     "population, exclusions, owner and version. An automated gate asserts that every "
     "registered metric is implemented and that no metric returns a population its "
     "own definition excludes."),
    ("security",
     "Entitlements are enforced by a PostgreSQL row-level policy on the project "
     "dimension, which every metric view reaches through. A dashboard filter is not "
     "a security boundary. The policy is fail-closed: an unset scope returns no rows."),
    ("assistant",
     "The assistant resolves questions against the metric catalogue and calls governed "
     "tools. It never writes SQL, never infers permission, and abstains when a term "
     "maps to more than one registered metric."),
    ("quality",
     "Data quality runs in three tiers. Ingestion checks judge what the source sent "
     "and quarantine bad rows. Core checks judge whether the canonical model is "
     "coherent. Metric checks judge whether the calculation layer agrees with the "
     "data beneath it."),
]

USER_GUIDES = [
    ("fiscal-calendar",
     "The fiscal year starts on 1 October. FY26 runs from October 2025 to September "
     "2026. Projects are attributed to the fiscal year in which they completed, so a "
     "project starting in FY25 and finishing in FY26 counts towards FY26."),
    ("reading-box-plots",
     "A cycle-time box plot shows the spread, not just the average. The box spans P25 "
     "to P75, the line is the median, and the upper whisker is P90 rather than the "
     "maximum because the long tail is the interesting part. Always check the sample "
     "size before comparing two boxes."),
    ("filters",
     "Governed filter dimensions are fiscal year, transfer type, portfolio, complexity "
     "class, source site and target site. Filters are resolved from governed metadata, "
     "so the assistant can apply them without the user knowing which ones exist."),
    ("completed-vs-open",
     "Completed and in-progress projects must not be mixed in a distribution. A cohort "
     "of open projects has no cycle time yet, and including them understates the "
     "median. Every panel states the population it covers."),
    ("forecast-horizons",
     "Forecast accuracy is measured at controlled horizons -- how far before completion "
     "the forecast was made. Measuring only the latest forecast makes any organisation "
     "look accurate, because forecasts get revised as reality becomes obvious."),
    ("ambiguous-late",
     "The word 'late' is ambiguous. It can mean schedule deviation (the plan moved from "
     "the baseline), completion variance (the project finished after its baseline), or "
     "forecast error (it finished later than forecast). These answer different questions "
     "and give different numbers."),
    ("rebaselining",
     "Repeated re-baselining can make a portfolio look healthier than it is, because "
     "each replan moves the target being measured against. The original baseline is "
     "kept immutable so that drift stays visible."),
]

DASHBOARD_METADATA = [
    ("management-overview", "ACTUAL_TRANSFER_CYCLE_TIME",
     "The management view shows open transfers, how many are on track, at risk or late, "
     "median cycle time and completed transfers per fiscal year. Health bands come from "
     "the project status mart, defined once in SQL."),
    ("cycle-time-distribution", "CYCLE_TIME_DISTRIBUTION",
     "The cycle-time panel is a box plot of completed-project duration, breakable down "
     "by fiscal year, transfer type, portfolio, complexity or site."),
    ("schedule-performance", "BASELINE_FINISH_DEVIATION_DAYS",
     "The schedule panel compares the frozen baseline finish with the latest replan, "
     "grouped by transfer type, and lists the open projects with the largest slip."),
    ("forecast-accuracy", "FORECAST_ERROR_DAYS",
     "The forecast panel buckets error by how far before completion the forecast was "
     "made, and plots bias alongside absolute error to expose systematic optimism."),
    ("bottlenecks", "STAGE_CYCLE_TIME",
     "The bottleneck panel shows milestone-to-milestone durations, locating where in "
     "the transfer process delay is created rather than only that the total is large."),
    ("project-drilldown", "BASELINE_FINISH_DEVIATION_DAYS",
     "The drill-down plots every preserved schedule revision against the frozen "
     "baseline for a single project, with its milestones and snapshots."),
]


def metric_documents(catalogue_rows):
    """
    Turn each registered metric into a retrievable document.

    Generated, never hand-written: the text restates the catalogue verbatim, so
    the knowledge base cannot drift from the metric layer it describes.
    """
    docs = []
    for m in catalogue_rows:
        text = (
            f"{m['business_name']} (metric code {m['metric_code']}, "
            f"version {m['version']}) is defined as {m['definition']}. "
            f"It is measured at {m['grain']} grain in {m['unit']}. "
            f"Population: {m['population']}. Excludes: {m['exclusions']}. "
            f"Owned by {m['owner']}, effective from {m['effective_from']}.")
        docs.append({
            "collection": "metric_definitions",
            "doc_id": m["metric_code"],
            "metric_code": m["metric_code"],
            "title": m["business_name"],
            "text": text,
            "source": "tr_gov.metric_definition",
        })
    return docs


def curated_documents():
    docs = []
    for doc_id, text in ARCHITECTURE_DOCS:
        docs.append({"collection": "architecture_docs", "doc_id": doc_id,
                     "metric_code": None, "title": doc_id.replace("-", " ").title(),
                     "text": text, "source": "curated"})
    for doc_id, text in USER_GUIDES:
        docs.append({"collection": "user_guides", "doc_id": doc_id,
                     "metric_code": None, "title": doc_id.replace("-", " ").title(),
                     "text": text, "source": "curated"})
    for doc_id, metric, text in DASHBOARD_METADATA:
        docs.append({"collection": "dashboard_metadata", "doc_id": doc_id,
                     "metric_code": metric, "title": doc_id.replace("-", " ").title(),
                     "text": text, "source": "bi/static/app.js"})
    return docs


def all_documents(catalogue_rows):
    return metric_documents(catalogue_rows) + curated_documents()


COLLECTIONS = ["metric_definitions", "dashboard_metadata",
               "architecture_docs", "user_guides"]
