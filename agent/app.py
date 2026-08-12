"""
Transfer & Conversion Intelligence Platform :: the self-explaining reporting assistant.

    POST /ask   {"question": "which transfer type has the highest cycle time?"}

The pipeline is the one the architecture spec argues for, with every authority
outside the language layer:

    question -> resolve (catalogue vocabulary) -> MetricQuery (validated)
             -> execute (read-only governed API) -> explain (with provenance)
             -> audit

It answers with no LLM at all, which is the point rather than a limitation: metric
resolution, filters, permissions and arithmetic are deterministic, so they are
testable and cannot hallucinate. A model can be added later for phrasing that the
resolver misses -- it would still have to emit a MetricQuery, and would still be
bounded by the same catalogue.

Run:
    uvicorn agent.app:app --port 8100 --reload
"""
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import audit, explain, resolver  # noqa: E402
from agent.executor import Executor  # noqa: E402
from agent.schema import Intent  # noqa: E402
from observability import telemetry  # noqa: E402

API_BASE = os.environ.get("TRANSFEROPS_API", "http://127.0.0.1:8000")

app = FastAPI(
    title="Transfer & Conversion Intelligence Platform Reporting Assistant",
    description="Read-only, catalogue-bound analytics assistant.",
    version="0.1.0",
)


class ApiClient:
    """Thin wrapper so the agent can be driven in-process during tests."""

    def __init__(self, base_url=API_BASE, client=None, identity=None):
        self.identity = identity
        self._client = client or httpx.Client(base_url=base_url, timeout=30.0)

    def get(self, path, **params):
        headers = {"X-Demo-User": self.identity} if self.identity else {}
        clean = {k: v for k, v in params.items() if v is not None}
        r = self._client.get(path, params=clean, headers=headers)
        r.raise_for_status()
        return r.json()

    def catalogue(self):
        return self.get("/catalogue")["metrics"]


class Question(BaseModel):
    question: str
    identity: str | None = None
    # deterministic | llm | auto. See `answer()` for what each one promises.
    mode: str = "auto"


# The abstention reasons that may be escalated to a model, and the ones that may
# never be. This is the security boundary of the two-mode design, so it is a
# table rather than an `if` buried in the escalation path.
#
#   out_of_scope      -> escalate. The resolver's vocabulary missed a phrasing;
#                        a model may find the metric. This is the whole reason
#                        the LLM mode exists.
#   ambiguous         -> never. The question maps to several governed metrics,
#                        and offering the three is the *correct* answer. Handing
#                        it to a model to pick one is precisely the silent choice
#                        that ends with a management meeting arguing about whose
#                        number is right.
#   action_requested  -> never. The assistant is read-only. A model cannot be
#                        given an authority the platform does not have.
#   injection         -> never. Escalating a detected injection attempt to a less
#                        deterministic component is the one thing that must not
#                        happen; the refusal is the answer.
ESCALATABLE = {"out_of_scope"}


def _classify_abstention(query):
    """Why the assistant declined -- the label that makes abstentions readable."""
    reason = (query.reason or "").lower()
    if "instruction-override" in reason or "sql-manipulation" in reason:
        return "injection", "injection"
    if "read-only" in reason:
        return "action_requested", "action"
    if "more than one governed metric" in reason:
        return "ambiguous", None
    return "out_of_scope", None


_STORE = None


def knowledge_store(api):
    """
    Lazily build the semantic knowledge base from the live catalogue.

    Built from `tr_gov.metric_definition` rather than from a hand-written
    glossary, so a retrieved explanation cannot contradict the metric it
    explains. Retrieval failing is never fatal: the assistant answers from the
    catalogue as before, just without supporting context.
    """
    global _STORE
    if _STORE is None:
        try:
            from rag.store import KnowledgeStore
            store = KnowledgeStore()
            store.build(api.catalogue())
            _STORE = store
        except Exception:
            _STORE = False
    return _STORE or None


def _llm_answer(question, api, identity, started, fallback_from=None):
    """
    The tool-calling path: a model chooses which governed tool to call.

    Bounded by the same catalogue as the resolver -- it picks an endpoint from a
    closed list and never writes a query -- but it is not deterministic, so the
    reply says which mode produced it. A reader should always be able to tell
    whether a number was reached by a rule or by a model.
    """
    from ai import ask as llm_ask

    result = llm_ask.answer(api, question, filters=None)
    elapsed = time.perf_counter() - started

    telemetry.AGENT_LATENCY.observe(elapsed)
    telemetry.AGENT_QUESTIONS.labels(intent="llm", outcome="answered").inc()
    for call in result.get("trace") or []:
        telemetry.AGENT_TOOL_CALLS.labels(
            tool=call.get("tool", "unknown"),
            outcome="empty" if not call.get("rows") else "ok").inc()

    audit.record({
        "asked_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "question": question,
        "resolved_metric": None,
        "metric_version": None,
        "intent": "llm",
        "filters": result.get("filters") or {},
        "tool_called": ",".join(c.get("tool", "") for c in result.get("trace") or []),
        "rows_returned": sum(c.get("rows", 0) for c in result.get("trace") or []),
        "duration_ms": int(elapsed * 1000),
        "abstained": False,
        # A model-written answer has a trace, not a governed provenance
        # envelope. Claiming otherwise would make the two modes indistinguishable
        # in the audit trail, which is the one place they must not be.
        "provenance_complete": False,
    })
    return {**result, "mode": "llm", "escalated_from": fallback_from}


def answer(question, api=None, identity=None, retrieve=True, mode="deterministic"):
    """
    The whole pipeline, importable so tests and evals share one code path.

    Three modes, selectable per request:

      * **deterministic** (the default, and what the eval set scores) -- the
        catalogue-bound resolver, no model involved. Testable, non-hallucinating,
        and it abstains rather than guessing.
      * **llm** -- a model picks which governed tool to call. Wider vocabulary,
        weaker guarantees; the trace comes back with the answer.
      * **auto** -- deterministic first; escalate to the model only when the
        resolver simply did not recognise the phrasing. Ambiguity, action
        requests and injection attempts are never escalated (see ESCALATABLE) --
        for those, the refusal *is* the correct answer, and passing them to a
        less deterministic component would undo the reason they were caught.

    The default stays deterministic so `make evals` scores the deterministic
    resolver whether or not a model happens to be configured in the environment
    it runs in. The HTTP endpoint defaults to `auto`.
    """
    started = time.perf_counter()
    api = api or ApiClient(identity=identity)

    if mode == "llm":
        return _llm_answer(question, api, identity, started)

    ex = Executor(api)

    query = resolver.resolve(question, ex.codes())

    # Retrieval runs AFTER resolution and never changes it. It cannot rescue a
    # refusal into an answer, promote a clarification into a guess, or supply a
    # number -- it only attaches documents that help a human understand the
    # reply. Authority stays with the catalogue and the governed tools.
    if retrieve and query.intent in (Intent.DEFINE, Intent.REFUSE):
        store = knowledge_store(api)
        if store is not None:
            try:
                query.sources = store.search(question, limit=3)
            except Exception:
                query.sources = []

    payload, tool = ex.execute(query)
    result = explain.build(query, payload, tool, ex.catalogue())
    elapsed = time.perf_counter() - started

    abstained = not query.is_actionable()
    outcome = "abstained" if abstained else "answered"
    telemetry.AGENT_LATENCY.observe(elapsed)
    telemetry.AGENT_QUESTIONS.labels(intent=query.intent.value, outcome=outcome).inc()
    telemetry.AGENT_PROVENANCE.labels(
        complete=str(bool(result.get("provenance_complete"))).lower()).inc()

    if abstained:
        reason, security_kind = _classify_abstention(query)
        telemetry.AGENT_ABSTENTIONS.labels(reason=reason).inc()
        if security_kind:
            telemetry.AGENT_SECURITY_EVENTS.labels(kind=security_kind).inc()

        # The escalation point. Only an unrecognised phrasing gets a second
        # opinion, and only when a model is actually configured -- so a
        # deployment without one behaves exactly as it did before this existed.
        if mode == "auto" and reason in ESCALATABLE:
            try:
                from ai import gateway as ai_gateway
                if ai_gateway.configured():
                    return _llm_answer(question, api, identity, started,
                                       fallback_from=reason)
            except Exception:  # noqa: BLE001
                # A model that is unreachable or misconfigured must not turn an
                # honest abstention into an error. The deterministic refusal
                # below is still a correct answer.
                pass
    elif query.metric_code:
        telemetry.AGENT_METRIC_RESOLVED.labels(metric_code=query.metric_code).inc()

    if tool:
        telemetry.AGENT_TOOL_CALLS.labels(
            tool=tool, outcome="ok" if payload is not None else "empty").inc()

    audit.record({
        "asked_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "question": question,
        "resolved_metric": query.metric_code,
        "metric_version": (result.get("metric") or {}).get("version"),
        "intent": query.intent.value,
        "filters": query.filters,
        "tool_called": tool,
        "rows_returned": len(result.get("rows", []) or []),
        "duration_ms": int(elapsed * 1000),
        "abstained": abstained,
        "provenance_complete": bool(result.get("provenance_complete")),
    })
    return {**result, "mode": "deterministic"}


@app.post("/ask", tags=["assistant"])
def ask(q: Question):
    """
    Ask the assistant.

    `mode` defaults to `auto`: the deterministic resolver answers what it can
    resolve, and only an unrecognised phrasing is passed to a model. Send
    `"mode": "deterministic"` to pin the guaranteed path, or `"llm"` to compare
    the two on the same question -- which is the point of shipping both.
    """
    if q.mode not in ("deterministic", "llm", "auto"):
        return {"error": "mode must be deterministic, llm or auto"}
    return answer(q.question, identity=q.identity, mode=q.mode)


@app.get("/modes", tags=["assistant"])
def modes():
    """Which answering modes this deployment can actually offer."""
    try:
        from ai import gateway as ai_gateway
        ai = ai_gateway.describe()
    except Exception as exc:  # noqa: BLE001
        ai = {"configured": False, "detail": str(exc)}
    return {
        "default": "auto",
        "available": ["deterministic"] + (["llm", "auto"] if ai.get("configured") else []),
        "ai": ai,
    }


@app.get("/audit", tags=["assistant"])
def audit_trail(limit: int = 50):
    """Every call, with its resolution and tool. Provenance is not optional --
    an answer no one can trace back is not usable for a management decision."""
    return {"calls": audit.recent(limit), **audit.status()}


@app.get("/observability/metrics", tags=["service"], include_in_schema=False)
def prometheus_metrics():
    payload, content_type = telemetry.render()
    return Response(content=payload, media_type=content_type)


@app.get("/health", tags=["service"])
def health():
    try:
        ex = Executor(ApiClient())
        return {"status": "healthy", "metrics_known": len(ex.codes())}
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)}
