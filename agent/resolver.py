"""
Transfer & Conversion Intelligence Platform :: question -> MetricQuery.

Resolution is deterministic and reads its vocabulary from `tr_gov.metric_definition`
via the API. That ordering is deliberate: the catalogue is the authority on what a
metric means, so the resolver cannot invent a definition even in principle. An LLM
can be layered on later for phrasing that this misses, but it would still have to
emit a MetricQuery and would still be bounded by the same catalogue -- so the
governed path is the default rather than the fallback.

The interesting behaviour here is refusing to guess. "Which projects are late?" is
genuinely ambiguous across three registered metrics, and picking one silently is
how a management conversation ends up arguing about whose number is right.
"""
import re

from .schema import Aggregation, Intent, MetricQuery

# Business vocabulary -> registered metric code. Synonyms are what users actually
# type; the metric_code is what the platform agrees the words mean.
ALIASES = {
    "ACTUAL_TRANSFER_CYCLE_TIME": [
        "cycle time", "cycle-time", "transfer duration", "project duration",
        "how long", "lead time", "turnaround", "time to complete", "duration",
    ],
    "BASELINE_FINISH_DEVIATION_DAYS": [
        "schedule drift", "schedule deviation", "baseline deviation", "slip",
        "slippage", "behind baseline", "original vs latest", "plan movement",
        "rebaseline", "drift",
    ],
    "COMPLETION_VARIANCE_DAYS": [
        "completion variance", "finished late", "overran", "missed baseline",
        "delivery variance",
    ],
    "FORECAST_ERROR_DAYS": [
        "forecast error", "forecast accuracy", "forecast quality", "predictability",
        "how accurate", "forecast bias",
    ],
    "FORECAST_CYCLE_TIME": [
        "forecast cycle time", "expected duration", "projected duration",
        "expected cycle time",
    ],
    "STAGE_CYCLE_TIME": [
        "stage", "milestone", "bottleneck", "which step", "where is the delay",
        "phase",
    ],
    "TRANSFER_THROUGHPUT": [
        "throughput", "how many completed", "how many transfers", "completions",
        "volume", "delivered", "did we complete",
    ],
    "ON_TIME_COMPLETION_RATE": [
        "on time", "on-time", "on time rate", "hit the date", "met baseline",
    ],
    "CYCLE_TIME_DISTRIBUTION": [
        "distribution", "box plot", "boxplot", "spread", "percentile", "variability",
        "p90", "p75", "quartile",
    ],
}

# Words that are ambiguous *across* governed metrics. Listing them explicitly is
# the mechanism that turns a guess into a question.
AMBIGUOUS = {
    "late": ["BASELINE_FINISH_DEVIATION_DAYS", "COMPLETION_VARIANCE_DAYS",
             "FORECAST_ERROR_DAYS"],
    "delay": ["BASELINE_FINISH_DEVIATION_DAYS", "COMPLETION_VARIANCE_DAYS",
              "STAGE_CYCLE_TIME"],
    "delayed": ["BASELINE_FINISH_DEVIATION_DAYS", "COMPLETION_VARIANCE_DAYS"],
    "behind": ["BASELINE_FINISH_DEVIATION_DAYS", "COMPLETION_VARIANCE_DAYS"],
    "performance": ["ACTUAL_TRANSFER_CYCLE_TIME", "ON_TIME_COMPLETION_RATE",
                    "BASELINE_FINISH_DEVIATION_DAYS"],
}

GROUP_WORDS = {
    "fiscal_year": ["fiscal year", "by year", "per year", "by fy", "year on year"],
    "transfer_type": ["transfer type", "by type", "kind of transfer"],
    "portfolio": ["portfolio", "business unit", "division"],
    "complexity_class": ["complexity"],
    "source_site": ["source site", "from site", "origin"],
    "target_site": ["target site", "to site", "destination", "receiving site"],
}

AGG_WORDS = {
    Aggregation.P90: ["p90", "90th", "worst case", "tail", "long tail"],
    Aggregation.P75: ["p75", "75th", "upper quartile"],
    Aggregation.P25: ["p25", "25th", "lower quartile", "best case"],
    Aggregation.COUNT: ["how many", "count", "number of"],
    # "mean" is deliberately absent: in this domain it appears far more often in
    # "what does X mean?" than as a request for an average.
    Aggregation.MEDIAN: ["median", "typical", "average", "usual"],
}

SITES = ["villach", "dresden", "regensburg", "kulim", "batam", "melaka",
         "wuxi", "dublin"]
PORTFOLIOS = {"pf_auto": "PF_AUTO", "automotive": "PF_AUTO",
              "pf_power": "PF_POWER", "power": "PF_POWER",
              "pf_iot": "PF_IOT", "iot": "PF_IOT", "connected": "PF_IOT"}
TRANSFER_TYPES = ["fab_to_fab", "int_to_foundry", "foundry_to_int", "assy_move",
                  "node_conversion"]

# Instruction-shaped text arriving from data (project names, change reasons, docs)
# is data, never instruction. This is a defence in depth measure: the executor
# already cannot run arbitrary SQL, but a question carrying an override attempt
# should be refused loudly so it shows up in the audit trail.
INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above)|disregard .{0,20}instruction|"
    r"system prompt|you are now|reveal .{0,20}(prompt|credentials|password)|"
    r"drop table|delete from|insert into|update .{0,30}set |grant |;--",
    re.IGNORECASE)

# The assistant is advisory and read-only in its first release: it explains and
# analyses, it never changes a schedule, approves a baseline or edits a record.
# An action request is refused outright rather than quietly answered as a query.
ACTION = re.compile(
    r"\b(approve|reject|authorise|authorize|update|modify|change|edit|set|delete|"
    r"remove|create|insert|assign|close|reopen|reschedule|re-?baseline the)\b",
    re.IGNORECASE)

# A definition is asked for with explicit markers. Bare "what is ...?" is a request
# for a *value* ("what is our on-time rate?"), not for a definition.
DEFINE = re.compile(
    r"\b(define|definition of|meaning of|explain)\b|\bwhat does\b.{0,60}\bmean\b",
    re.IGNORECASE)

# Enumeration is about projects specifically; "show me the drift by type" is a
# grouped metric question, not a list of rows.
LIST_RE = re.compile(
    r"\b(which|list|show|give me)\b.{0,40}\bprojects?\b|"
    r"\bprojects?\b.{0,40}\b(behind|past|over|more than|at risk)\b",
    re.IGNORECASE)


def _match_aliases(text):
    """All metrics whose vocabulary appears in the question, longest phrase first."""
    hits = []
    for code, words in ALIASES.items():
        for w in sorted(words, key=len, reverse=True):
            if w in text:
                hits.append((len(w), code))
                break
    return [code for _, code in sorted(hits, reverse=True)]


def _extract_filters(text):
    filters = {}
    fy = re.search(r"\bfy\s?(\d{2,4})\b", text)
    if fy:
        y = int(fy.group(1))
        filters["fiscal_year"] = 2000 + y if y < 100 else y
    elif (yr := re.search(r"\b(20\d{2})\b", text)):
        filters["fiscal_year"] = int(yr.group(1))

    for word, code in PORTFOLIOS.items():
        if word in text:
            filters["portfolio"] = code
            break
    for t in TRANSFER_TYPES:
        if t.replace("_", " ") in text or t in text:
            filters["transfer_type"] = t.upper()
            break
    for s in SITES:
        if s in text:
            filters["target_site"] = s.title()
            break
    for status in ("active", "completed", "planned", "cancelled"):
        if re.search(rf"\b{status}\b", text):
            filters["status"] = status.upper()
            break
    return filters


def _extract_group_by(text):
    for dim, words in GROUP_WORDS.items():
        if any(w in text for w in words):
            return dim
    return None


def _extract_aggregation(text):
    for agg, words in AGG_WORDS.items():
        if any(w in text for w in words):
            return agg
    return Aggregation.MEDIAN


def resolve(question, catalogue_codes):
    """Turn a natural-language question into a validated, inspectable MetricQuery."""
    text = " " + question.lower().strip() + " "

    if INJECTION.search(question):
        return MetricQuery(
            intent=Intent.REFUSE, question=question,
            reason="The request contains instruction-override or SQL-manipulation "
                   "text. Content from users and from project records is treated as "
                   "data, never as instructions.")

    if ACTION.search(text):
        return MetricQuery(
            intent=Intent.REFUSE, question=question,
            reason="This assistant is read-only. It explains and analyses governed "
                   "metrics; it cannot approve, reschedule or change project "
                   "records. Raise that through the transfer-management process.")

    # "What does X mean?" is answered from the catalogue, no query needed.
    if DEFINE.search(text):
        codes = _match_aliases(text)
        return MetricQuery(
            intent=Intent.DEFINE, question=question,
            metric_code=codes[0] if codes else None,
            candidates=codes[:3],
            reason="" if codes else "No registered metric matches that term.")

    # Ambiguity check runs before matching, so a vague word cannot be resolved by
    # a coincidental alias hit elsewhere in the sentence.
    for word, candidates in AMBIGUOUS.items():
        if re.search(rf"\b{word}\b", text) and not _match_aliases(text):
            return MetricQuery(
                intent=Intent.CLARIFY, question=question, candidates=candidates,
                reason=f'"{word}" maps to more than one governed metric. '
                       f"Choosing one silently would change the answer.")

    codes = _match_aliases(text)
    if not codes:
        return MetricQuery(
            intent=Intent.REFUSE, question=question,
            reason="No governed metric matches that question. The assistant only "
                   "answers from the registered metric catalogue.")

    metric_code = codes[0]
    if metric_code not in catalogue_codes:
        return MetricQuery(
            intent=Intent.REFUSE, question=question,
            reason=f"{metric_code} is not registered in this warehouse.")

    filters = _extract_filters(text)
    group_by = _extract_group_by(text)
    aggregation = _extract_aggregation(text)

    intent = Intent.RETRIEVE
    threshold = None
    if re.search(r"\b(which|what)\b.*\b(highest|lowest|slowest|fastest|worst|best|most|least)\b", text):
        intent = Intent.RANK
        group_by = group_by or "transfer_type"
    elif re.search(r"\b(compare|versus|vs\.?|against)\b", text) or \
            len(re.findall(r"\bfy\s?\d{2,4}\b", text)) > 1:
        intent = Intent.COMPARE
        group_by = group_by or "fiscal_year"
        filters.pop("fiscal_year", None)
    elif LIST_RE.search(text):
        intent = Intent.LIST
        group_by = None
        if (m := re.search(r"(\d+)\s*days?", text)):
            threshold = int(m.group(1))

    return MetricQuery(
        intent=intent, metric_code=metric_code, aggregation=aggregation,
        group_by=group_by, filters=filters, threshold=threshold,
        candidates=codes[:3], question=question)
