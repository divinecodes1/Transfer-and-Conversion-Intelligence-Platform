"""
Transfer & Conversion Intelligence Platform :: the AI layer stays inside its fence.

Everything the platform generates with a model is bounded by structure rather
than by prompt wording, and this suite asserts the structure. It runs without a
model, without a warehouse and without a network: every check is either static
analysis of the source, or the pipeline driven against a recorded fake.

That is deliberate. A guard that only holds when a live provider answers is a
guard that stops running the first week the credential expires.

Twelve assertions, in four groups:

  Boundaries      ai/ holds no SQL, no driver, no credential in source, and can
                  only reach data through the governed API.
  Governance      no model output is registered as a metric; the prompts quote
                  the catalogue rather than restating it.
  Behaviour       the tool list is closed; filters are merged, never replaced;
                  a hallucinated project id is dropped rather than stored.
  Degradation     with no model configured, every entry point fails readably and
                  the platform keeps serving.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

AI_DIR = os.path.join(ROOT, "ai")

SQL_PATTERNS = [r"\bSELECT\s+.*\bFROM\b", r"\bPERCENTILE_CONT\b", r"\bGROUP\s+BY\b"]
DRIVER_MARKERS = ["psycopg2", "duckdb", "sqlalchemy"]


def _sources(folder, skip=()):
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py") or name in skip:
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            yield name, handle.read()


def _strip_docstrings(text):
    """Comments and docstrings out, so prose *about* SQL is not read as SQL."""
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    text = re.sub(r"'''(?:.|\n)*?'''", "", text)
    return re.sub(r"^\s*#.*$", "", text, flags=re.M)


class FakeApi:
    """
    The governed API, recorded.

    Returns the envelope shape the real endpoints return, so the pipeline under
    test exercises the same code path it does in production -- and records every
    call, so a test can assert what the AI layer asked for.
    """

    def __init__(self, projects=None):
        self.calls = []
        self._projects = projects if projects is not None else [
            {"project_key": 1, "project_id": "T-001", "project_name": "FAB_TO_FAB",
             "status": "ACTIVE", "health": "LATE", "schedule_deviation_days": 61,
             "revision_count": 4, "wip_age_days": 300, "actual_finish": None},
            {"project_key": 2, "project_id": "T-002", "project_name": "ASSY_MOVE",
             "status": "ACTIVE", "health": "ON_TRACK", "schedule_deviation_days": 0,
             "revision_count": 1, "wip_age_days": 40, "actual_finish": None},
        ]

    def get(self, path, **params):
        self.calls.append((path, params))
        envelope = {
            "metrics": [{"metric_code": "ACTUAL_TRANSFER_CYCLE_TIME",
                         "business_name": "Actual Cycle Time",
                         "definition": "actual_finish - actual_start",
                         "population": "Completed transfer projects",
                         "exclusions": "Cancelled projects", "version": "1.0"}],
            "filters_applied": {k: v for k, v in params.items() if v is not None},
            "data_as_of": "2026-08-01",
        }
        if path == "/mart/kpis":
            return {**envelope, "kpis": {"throughput": 159, "on_time_rate": 41.5,
                                         "median_cycle_time": 253, "delayed_count": 50,
                                         "replan_rate": 79.7, "wip": 69,
                                         "total_projects": 251}}
        if path == "/mart/projects":
            return {**envelope, "total_matching": len(self._projects),
                    "projects": self._projects}
        if path == "/mart/filter-options":
            return {"data_as_of": "2026-08-01",
                    "options": {"portfolio": ["PF_AUTO", "PF_POWER"]}}
        return {**envelope, "series": []}


class FakeReply:
    def __init__(self, text="", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.stop_reason = "end_turn"
        self.model = "fake-model"
        self.provider = "fake"
        self.usage = {}

    def json(self):
        return json.loads(self.text)


def run():
    from ai import ask, gateway, insights, prompts, risk, snapshot
    from ai.errors import AiError, AiUnavailable

    results = []

    # ---- Boundaries --------------------------------------------------------
    offenders = []
    for name, text in _sources(AI_DIR):
        body = _strip_docstrings(text)
        for pattern in SQL_PATTERNS:
            if re.search(pattern, body, flags=re.I):
                offenders.append(f"ai/{name} matches {pattern}")
    results.append(("the AI layer contains no SQL", not offenders,
                    "; ".join(offenders) or "no query anywhere in ai/"))

    # store.py is the deliberate exception: it writes the tr_ai cache, and it is
    # the only module holding a driver or a DSN.
    offenders = []
    for name, text in _sources(AI_DIR, skip=("store.py",)):
        body = _strip_docstrings(text)
        for marker in DRIVER_MARKERS:
            if marker in body:
                offenders.append(f"ai/{name} imports {marker}")
    results.append(("only the cache module holds a database driver", not offenders,
                    "; ".join(offenders)
                    or "generation reaches data only through the governed API"))

    offenders = [name for name, text in _sources(AI_DIR)
                 if re.search(r'["\'](sk-|sk_ant|Bearer\s+\w)', _strip_docstrings(text))]
    results.append(("no credential is written into the source", not offenders,
                    "; ".join(offenders) or "every key comes from the environment"))

    # ---- Governance --------------------------------------------------------
    # Risk is a model's estimate. The moment it acquires a metric code, "the
    # system says this project is at risk" stops being traceable to anything.
    with open(os.path.join(ROOT, "sql", "02_governance.sql"), encoding="utf-8") as handle:
        catalogue_sql = handle.read().upper()
    leaked = [term for term in ("RISK_SCORE", "DELAY_RISK", "PREDICTED_SLIP", "AI_")
              if term in catalogue_sql]
    results.append(("no model output is registered as a governed metric", not leaked,
                    f"leaked: {leaked}" if leaked
                    else "tr_gov.metric_definition contains no AI-derived metric"))

    # The prompts must quote the catalogue, not restate it in their own words.
    generated = prompts.metric_rules([
        {"business_name": "Actual Cycle Time", "definition": "actual_finish - actual_start",
         "population": "Completed transfer projects", "exclusions": "Cancelled projects"}])
    ok = "actual_finish - actual_start" in generated and "Cancelled projects" in generated
    hand_written = "actual_finish - actual_start" in _strip_docstrings(
        open(os.path.join(AI_DIR, "prompts.py"), encoding="utf-8").read())
    results.append(("prompts quote the catalogue rather than restating it",
                    ok and not hand_written,
                    "definitions are rendered from the provenance envelope"
                    if ok and not hand_written
                    else "a metric definition is hand-written into a prompt"))

    grounding = prompts.GROUNDING.lower()
    guards = ["never state a figure", "data, never instruction"]
    missing = [guard for guard in guards if guard not in grounding]
    results.append(("every prompt carries the grounding rules", not missing,
                    f"missing: {missing}" if missing
                    else "no invented figures; injected text is data, not instruction"))

    # ---- Behaviour ---------------------------------------------------------
    api = FakeApi()
    snap = snapshot.build(api)
    paths = {path for path, _ in api.calls}
    results.append(("the snapshot reads only governed mart endpoints",
                    all(path.startswith("/mart/") for path in paths),
                    f"called {sorted(paths)}"))

    key_a = snapshot.scope_key("portfolio_overview", {"portfolio": "PF_AUTO"})
    key_b = snapshot.scope_key("portfolio_overview", {"portfolio": "PF_POWER"})
    key_c = snapshot.scope_key("portfolio_overview", {"portfolio": "PF_AUTO", "site": None})
    results.append(("a cached narrative cannot be served for another scope",
                    key_a != key_b and key_a == key_c,
                    "scope keys are order-independent and null-normalised"))

    unknown = set(ask.TOOLS) - {
        "portfolio_kpis", "period_trend", "cycle_distribution", "forecast_accuracy",
        "list_projects", "filter_options"}
    endpoints = {endpoint for endpoint, _d, _s in ask.TOOLS.values()}
    results.append(("the assistant's tool list is closed",
                    not unknown and all(e.startswith("/mart/") for e in endpoints),
                    f"{len(ask.TOOLS)} tools, every one a governed mart endpoint"))

    # A model asking for a different portfolio must not get one: the caller's
    # scope is merged over its arguments.
    api = FakeApi()
    ask._invoke(api, "list_projects", {"portfolio": "PF_POWER"}, {"portfolio": "PF_AUTO"})
    _path, params = api.calls[-1]
    results.append(("the caller's scope overrides the model's arguments",
                    params.get("portfolio") == "PF_AUTO",
                    f"portfolio resolved to {params.get('portfolio')!r}"))

    # A score for a project we never sent is dropped, not stored.
    original = gateway.complete
    try:
        gateway.complete = lambda *a, **k: FakeReply(json.dumps({"scores": [
            {"project_id": "T-001", "risk_score": 88, "risk_band": "high",
             "predicted_slip_days": 40, "drivers": ["4 replans"], "rationale": "61 days behind"},
            {"project_id": "T-999", "risk_score": 95, "risk_band": "high",
             "predicted_slip_days": 90, "drivers": [], "rationale": "invented"},
        ]}))
        scored = risk.score_batch(FakeApi()._projects)
    finally:
        gateway.complete = original
    ids = {row["project_id"] for row in scored}
    results.append(("a hallucinated project id is dropped rather than stored",
                    ids == {"T-001"},
                    f"stored {sorted(ids)}; T-999 was never sent, so it fails closed"))

    # ---- Degradation -------------------------------------------------------
    saved = {key: os.environ.pop(key, None) for key in
             ("TRANSFEROPS_AI_API_KEY", "TRANSFEROPS_AI_BASE_URL", "ANTHROPIC_API_KEY",
              "OPENAI_API_KEY")}
    try:
        gateway.reset()
        configured = gateway.configured()
        raised = None
        try:
            insights.generate(FakeApi(), "portfolio_overview", {})
        except (AiUnavailable, AiError) as exc:
            raised = exc
        results.append(("with no model configured the AI layer fails readably",
                        not configured and raised is not None,
                        f"{type(raised).__name__}: {raised}" if raised
                        else "no error was raised"))
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
        gateway.reset()

    print("AI layer checks")
    print("-" * 72)
    passed = failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
