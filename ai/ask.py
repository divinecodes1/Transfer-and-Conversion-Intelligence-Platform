"""
Transfer & Conversion Intelligence Platform :: the tool-calling assistant.

The LLM half of the two-mode assistant. The model chooses *which* governed
endpoint to call and with what filters; it never chooses what a metric means, and
it never reaches a database. The loop is written out here rather than delegated
to an SDK helper for one reason: the executor is the trust boundary, and a
boundary you can read in forty lines is a boundary you can argue about.

    question -> model picks a tool -> WE call the governed API -> result back
             -> ... -> answer, with the full trace attached

Four properties, each asserted in `tests/ai_checks.py`:

  * **The tool list is closed.** Six tools, each mapping to one governed
    endpoint written in this file. The model cannot name a path.
  * **Filters are merged, never replaced.** The caller's dashboard scope is
    applied on top of whatever the model asked for, so a question cannot widen
    the scope past what the reader is entitled to -- and the entitlement itself
    is enforced below this, at the row-level policy, not here.
  * **Every call is recorded.** The trace of tool, arguments and row count is
    returned alongside the answer and shown in the UI. An answer whose working
    is not inspectable is not usable for a management decision.
  * **It is read-only.** There is no tool that writes. "Approve the rebaseline"
    has nothing to call.
"""
from . import gateway, prompts, snapshot as snap
from .errors import AiError

MAX_STEPS = 8

_FILTER_PROPERTIES = {
    "fiscal_year": {"type": ["integer", "null"],
                    "description": "Fiscal year of completion; FY starts 1 October."},
    "site": {"type": ["string", "null"],
             "description": "Matches either the source or the target site."},
    "transfer_type": {"type": ["string", "null"]},
    "portfolio": {"type": ["string", "null"]},
    "complexity": {"type": ["string", "null"],
                   "description": "Complexity class: LOW, MED or HIGH."},
}


def _schema(extra=None, required=()):
    return {
        "type": "object",
        "properties": {**_FILTER_PROPERTIES, **(extra or {})},
        "required": list(required),
        "additionalProperties": False,
    }


# name -> (endpoint, description, schema). The endpoint column is the whole
# security model: it is data in this file, never a value the model produced.
TOOLS = {
    "portfolio_kpis": (
        "/mart/kpis",
        "Headline KPIs for a scope: throughput, work in progress, median and P90 "
        "cycle time, on-time rate, replan rate, median WIP age, median schedule "
        "deviation and the count of delayed projects.",
        _schema(),
    ),
    "period_trend": (
        "/mart/trend",
        "Fiscal-year trend of throughput, median cycle time, on-time rate and "
        "replan rate. Use for questions about direction over time.",
        _schema(),
    ),
    "cycle_distribution": (
        "/mart/distribution",
        "Cycle-time percentiles (min, P25, median, P75, P90, max) per cohort. "
        "Use for questions about spread, or which cohort is slowest.",
        _schema({"group_by": {
            "type": "string",
            "enum": ["transfer_type", "complexity_class", "target_site",
                     "source_site", "portfolio", "fiscal_year"],
        }}, required=("group_by",)),
    ),
    "forecast_accuracy": (
        "/mart/accuracy",
        "Forecast error by how far before completion the forecast was made: "
        "bias, median and P90 absolute error, and the share landing within 14 days.",
        _schema(),
    ),
    "list_projects": (
        "/mart/projects",
        "Individual project rows. Use for questions about specific projects, "
        "worst performers, or counts of projects meeting a condition.",
        _schema({
            "search": {"type": ["string", "null"],
                       "description": "Free text over project id, name and target site."},
            "status": {"type": ["string", "null"],
                       "description": "PLANNED, ACTIVE or COMPLETED."},
            "health": {"type": ["string", "null"],
                       "description": "ON_TRACK, AT_RISK, LATE or UNKNOWN."},
            "sort_by": {"type": ["string", "null"],
                        "enum": ["actual_cycle_time_days", "schedule_deviation_days",
                                 "completion_variance_days", "revision_count",
                                 "wip_age_days", None]},
            "descending": {"type": ["boolean", "null"]},
        }),
    ),
    "filter_options": (
        "/mart/filter-options",
        "The values available for each filter dimension. Call this when you are "
        "unsure whether a site, portfolio or transfer type the user named exists.",
        {"type": "object", "properties": {}, "required": [],
         "additionalProperties": False},
    ),
}


def definitions():
    """The tool list, in the gateway's provider-neutral shape."""
    return [{"name": name, "description": description, "parameters": schema}
            for name, (_endpoint, description, schema) in TOOLS.items()]


def _rows_of(payload):
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else []
    for key in ("series", "projects"):
        if key in payload:
            return payload[key] or []
    if "kpis" in payload:
        return [payload["kpis"]] if payload["kpis"] else []
    if "options" in payload:
        return [payload["options"]]
    return []


def _invoke(api, name, arguments, scope):
    """
    Run one tool call.

    The caller's dashboard scope is applied *after* the model's arguments, so a
    model that asks for a different portfolio gets the reader's one. That is
    defence in depth rather than the fence -- the row-level policy is the fence,
    and it does not consult this function.
    """
    endpoint, _description, _schema_ = TOOLS[name]
    params = {k: v for k, v in (arguments or {}).items() if v is not None}
    params.update(snap.clean(scope))
    if name == "list_projects":
        params.setdefault("limit", 40)
    payload = api.get(endpoint, **params)
    return payload, _rows_of(payload)


def answer(api, question, filters=None, max_steps=MAX_STEPS):
    """
    Answer one question through the governed metric tools.

    Returns the answer, the trace of every tool call it took to get there, and
    the last result set -- so the UI can show the working and the table beside
    the prose.
    """
    question = (question or "").strip()
    if len(question) < 3:
        raise AiError("Ask a question of at least three characters.")

    scope = snap.clean(filters)
    system = prompts.ASK + (
        f"\n\nThe reader's active dashboard scope is: {snap.describe_scope(scope)}."
        if scope else "\n\nThe reader has no dashboard filters applied.")

    messages = [gateway.user(question)]
    trace, collected = [], []

    for _step in range(max_steps):
        reply = gateway.complete(system, messages, tools=definitions())
        if not reply.tool_calls:
            return {
                "answer": (reply.text or "").strip(),
                "trace": trace,
                "data": collected[-1] if collected else None,
                "model": reply.model,
                "provider": reply.provider,
                "filters": scope,
                "mode": "llm",
            }

        messages.append(gateway.assistant(reply))
        for call in reply.tool_calls:
            if call.name not in TOOLS:
                # The model named something that is not a tool. Told, not
                # crashed: it can recover on the next step, and the attempt is
                # visible in the trace rather than swallowed.
                trace.append({"tool": call.name, "arguments": call.arguments,
                              "rows": 0, "error": "unknown tool"})
                messages.append(gateway.tool_result(
                    call, f"No such tool. Available: {sorted(TOOLS)}"))
                continue
            try:
                payload, rows = _invoke(api, call.name, call.arguments, scope)
            except Exception as exc:  # noqa: BLE001 -- reported to the model
                trace.append({"tool": call.name, "arguments": call.arguments,
                              "rows": 0, "error": str(exc)})
                messages.append(gateway.tool_result(call, f"Tool failed: {exc}"))
                continue

            trace.append({"tool": call.name, "arguments": call.arguments,
                          "rows": len(rows)})
            if rows:
                collected.append({"source": call.name, "rows": rows[:60]})
            messages.append(gateway.tool_result(call, snap.serialise(payload, 12000)))

    # Out of steps. Saying so beats returning whatever half-formed thing the last
    # turn produced and letting a reader take it for a finished answer.
    raise AiError(
        f"The assistant did not settle on an answer within {max_steps} tool calls. "
        "Try a narrower question.")
