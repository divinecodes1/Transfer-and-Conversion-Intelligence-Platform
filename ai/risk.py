"""
Transfer & Conversion Intelligence Platform :: delay-risk scoring.

A score, a band, a predicted slip and the evidence the model says it used, for
each in-flight project. This is the one place in the platform where a *number*
comes out of a model, so it is fenced off from the metric layer harder than
anything else here:

  * **It is not a governed metric and is never registered as one.** It lives in
    `tr_ai.project_risk`, not `tr_metric`; `tests/ai_checks.py` asserts no risk
    field ever appears in `tr_gov.metric_definition`. A model's opinion that
    quietly acquires a metric code is how "the system says this project is at
    risk" stops being traceable to anything.

  * **It is presented as an estimate.** Every row carries the model that produced
    it, the warehouse vintage it was scored against, and a rationale quoting a
    governed number. A reader can check the claim against the register beside it.

  * **It cannot invent a project.** Scores come back keyed by `project_id`, and
    anything that does not match a project in the batch we sent is dropped
    rather than stored -- so a hallucinated identifier fails closed instead of
    appearing in the register as a project nobody can find.

Batched deliberately small. One prompt for the whole portfolio is cheaper per
project and worse at every one of them: quality degrades along a long list, and a
single failure loses every score rather than twelve.
"""
import time

from . import gateway, prompts
from .errors import AiError

BATCH = 12
DEFAULT_LIMIT = 60

# What the scorer is shown. Nothing that would let it reason about a project it
# was not given, and nothing it does not need -- a narrower prompt is a cheaper
# and more accurate one.
SCORING_COLUMNS = (
    "project_id", "project_name", "transfer_type", "complexity_class",
    "portfolio", "source_site", "target_site", "status", "health",
    "wip_age_days", "schedule_deviation_days", "revision_count",
    "was_replanned", "baseline_finish", "latest_finish",
    "latest_forecast_finish",
)


def _clamp(value, low, high, default=0):
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _band(explicit, score):
    """
    The band the model gave, or the one its own score implies.

    Deriving from the score rather than defaulting to "low" keeps the two fields
    from contradicting each other on screen, which is the only way a reader
    notices the model was inconsistent -- and the wrong way to notice.
    """
    band = str(explicit or "").strip().lower()
    if band in ("low", "medium", "high"):
        return band
    return "high" if score >= 67 else "medium" if score >= 34 else "low"


def in_flight(api, filters=None, limit=DEFAULT_LIMIT):
    """
    The projects worth scoring: started, not finished, oldest WIP first.

    Ordering by WIP age rather than taking an arbitrary slice means a capped run
    scores the projects most likely to be in trouble, not the first ones
    alphabetically.
    """
    from . import snapshot as snap
    payload = api.get("/mart/projects", status="ACTIVE", sort_by="wip_age_days",
                      descending=True, limit=limit, **snap.clean(filters))
    return [p for p in payload.get("projects") or []
            if p.get("actual_finish") in (None, "")]


def score_batch(projects):
    """Score one small batch. Returns rows ready for `tr_ai.project_risk`."""
    if not projects:
        return []

    known = {p.get("project_id"): p for p in projects}
    compact = [{k: _plain(p.get(k)) for k in SCORING_COLUMNS
                if p.get(k) is not None} for p in projects]

    reply = gateway.complete(
        prompts.RISK,
        [gateway.user(_dumps(compact))],
        json_schema=prompts.RISK_SCHEMA,
    )

    payload = reply.json()
    scores = payload.get("scores") if isinstance(payload, dict) else payload
    if not isinstance(scores, list):
        raise AiError("The model did not return a list of risk scores.")

    rows = []
    for item in scores:
        if not isinstance(item, dict):
            continue
        project = known.get(item.get("project_id"))
        if project is None:
            # A project_id we did not send. Dropping it is the fail-closed
            # choice: a score attached to an identifier nobody can look up is
            # worse than a project with no score.
            continue
        score = _clamp(item.get("risk_score"), 0, 100)
        rows.append({
            "project_key": project.get("project_key"),
            "project_id": project.get("project_id"),
            "risk_score": score,
            "risk_band": _band(item.get("risk_band"), score),
            "predicted_slip_days": _clamp(item.get("predicted_slip_days"),
                                          -365, 1095),
            "drivers": [str(d)[:80] for d in (item.get("drivers") or [])][:3],
            "rationale": str(item.get("rationale") or "")[:300],
            "model": reply.model,
            "provider": reply.provider,
        })
    return rows


def score(api, filters=None, limit=DEFAULT_LIMIT, deadline=None):
    """
    Score every in-flight project in scope, batch by batch.

    A failed batch does not fail the run: the projects it covered simply keep
    whatever score they had. A nightly job that abandons fifty good scores over
    one bad response is a job that quietly stops producing anything.

    `deadline` is a `time.monotonic()` value after which no further batch is
    started. On a throttled night each batch can sit in retry backoff for
    minutes, and this loop used to have no bound at all -- so the whole run was
    ended by the platform's timeout instead, mid-batch, with the run row left
    open. Scores already produced are returned either way.
    """
    projects = in_flight(api, filters, limit)
    rows, failures = [], []
    batches = range(0, len(projects), BATCH)
    stopped_early = None
    for index, start in enumerate(batches):
        if deadline is not None and time.monotonic() >= deadline:
            stopped_early = (f"stopped after {index} of {len(batches)} batch(es):"
                             f" the run budget was spent")
            break
        batch = projects[start:start + BATCH]
        try:
            rows.extend(score_batch(batch))
        except AiError as exc:
            failures.append(str(exc))
    return {"scored": rows, "considered": len(projects), "failures": failures,
            "stopped_early": stopped_early}


def _plain(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _dumps(value):
    import json
    return json.dumps(value, default=str, sort_keys=True)
