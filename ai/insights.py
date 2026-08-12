"""
Transfer & Conversion Intelligence Platform :: narratives over the governed metric layer.

Three kinds, one pipeline:

    filters -> governed snapshot -> prompt -> narrative -> cached with its vintage

`portfolio_overview` is the briefing on the overview screen, `report_summary` is
the narrative section of a management report, and `anomaly_watch` flags movement
worth an alert. They differ only in the task half of the prompt.

Two properties are worth stating plainly, because they are what make a generated
narrative safe to put next to a governed number:

  * **The narrative carries the same vintage as the numbers it describes.** It is
    stored with the `data_as_of` of the snapshot it was written from, and served
    only while that vintage still stands. A briefing about last week's warehouse
    shown beside this week's chart is worse than no briefing.

  * **A narrative is never a source.** Nothing downstream reads a number out of
    one. The highlights beside it come from the snapshot, not from parsing the
    prose the model wrote -- which is why the tiles cannot disagree with the
    chart even if the model miscounts in its own sentence.
"""
from . import gateway, prompts, snapshot as snap
from .errors import AiError

TTL_HOURS = 24


def _tone(label, value):
    """
    The colour of a highlight chip.

    Bands live here rather than in the browser for the same reason the health
    band lives in SQL: a threshold rendered in two places is a threshold about to
    be rendered two ways.
    """
    if value is None:
        return "muted"
    if label == "On-time":
        return "ok" if value >= 70 else "warn" if value >= 50 else "bad"
    if label == "Delayed":
        return "bad" if value > 0 else "ok"
    if label == "Replan rate":
        return "bad" if value >= 60 else "warn" if value >= 30 else "ok"
    return "muted"


def highlights(kpis):
    """
    The chips shown beside the narrative.

    Read straight from the snapshot -- never parsed out of the generated text.
    That is the whole reason a briefing can sit next to a KPI tile without the
    two contradicting each other.
    """
    if not kpis:
        return []

    def num(key):
        value = kpis.get(key)
        return None if value is None else round(float(value), 1)

    def fmt(value, suffix=""):
        if value is None:
            return "—"
        return f"{value:g}{suffix}"

    return [
        {"label": "Throughput", "value": fmt(num("throughput")),
         "tone": "muted"},
        {"label": "Median cycle", "value": fmt(num("median_cycle_time"), " d"),
         "tone": "muted"},
        {"label": "On-time", "value": fmt(num("on_time_rate"), "%"),
         "tone": _tone("On-time", num("on_time_rate"))},
        {"label": "Replan rate", "value": fmt(num("replan_rate"), "%"),
         "tone": _tone("Replan rate", num("replan_rate"))},
        {"label": "Delayed", "value": fmt(num("delayed_count")),
         "tone": _tone("Delayed", num("delayed_count"))},
    ]


def headline(text):
    """The first real line, stripped of markdown, for a card header."""
    for line in (text or "").splitlines():
        cleaned = line.strip().lstrip("#*-> ").replace("**", "").strip()
        if cleaned:
            return cleaned[:200]
    return None


def generate(api, kind, filters=None):
    """
    Write one narrative for one scope.

    Returns the record the cache stores and the API serves -- content, headline,
    highlights, model, and the warehouse vintage it describes.
    """
    if kind not in prompts.INSIGHT_KINDS:
        raise AiError(f"Unknown insight kind {kind!r}; expected one of "
                      f"{list(prompts.INSIGHT_KINDS)}.")

    snapshot = snap.build(api, filters)
    system = prompts.insight(kind, snapshot.get("definitions"))
    reply = gateway.complete(system, [gateway.user(
        f"Filter scope: {snap.describe_scope(filters)}\n\n"
        f"Governed metric snapshot (JSON):\n{snap.serialise(snapshot)}")])

    text = (reply.text or "").strip()
    if not text:
        raise AiError("The model returned an empty narrative.")

    return {
        "kind": kind,
        "filters": snapshot["filters"],
        "scope_key": snap.scope_key(kind, filters),
        "portfolio": snapshot["filters"].get("portfolio"),
        "headline": headline(text),
        "content": text,
        "highlights": highlights(snapshot.get("kpis")),
        "model": reply.model,
        "provider": reply.provider,
        "data_as_of": snapshot.get("data_as_of") or None,
    }
