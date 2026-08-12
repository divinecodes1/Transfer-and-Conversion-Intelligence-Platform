"""
Transfer & Conversion Intelligence Platform :: the AI layer.

Everything a model does in this platform happens here, and everything here obeys
the same rule: **the model may phrase a number, never produce one.** Each module
below takes its figures from the governed API -- the same endpoints the dashboards
call, under the same identity and the same row-level policy -- and the model is
handed those figures as data. There is no path from a prompt to the warehouse.

    gateway.py    one provider-agnostic chat client (OpenAI-compatible + Anthropic)
    snapshot.py   the governed metric snapshot every prompt is grounded in
    insights.py   portfolio briefing / report summary / anomaly watch
    risk.py       per-project delay-risk scoring
    email.py      audience-aware report email drafting
    ask.py        tool-calling question answering, bounded by the metric tools
    store.py      the tr_ai cache: insights, risk scores, run history
    refresh.py    the scheduled job that warms both caches

`ai/` is importable without a model configured. Every entry point raises
AiUnavailable with a readable reason instead, so the platform degrades to the
deterministic assistant and the hand-built dashboards rather than failing.
"""
from .errors import AiError, AiUnavailable  # noqa: F401

__all__ = ["AiError", "AiUnavailable"]
