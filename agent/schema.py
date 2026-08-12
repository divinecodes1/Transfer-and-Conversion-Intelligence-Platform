"""
Transfer & Conversion Intelligence Platform :: the metric query object.

This is the contract that replaces "let the model write SQL". A question becomes a
*structured, validated* MetricQuery; the executor -- trusted code, not the model --
turns that into a call against the governed API. Nothing the user or an LLM says
ever reaches the database as syntax.

Two consequences worth being explicit about:

  * The set of answerable questions is bounded by this schema. That is a feature.
    Enterprise text-to-SQL degrades badly on real schemas, and a wrong number
    delivered fluently is worse than an abstention.
  * Because the object is inspectable, the agent can show its interpretation
    before acting -- which is what "self-explaining" actually requires.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    DEFINE = "define"            # "what does schedule drift mean?"
    RETRIEVE = "retrieve"        # "median cycle time in FY26"
    COMPARE = "compare"          # "FY25 vs FY26"
    RANK = "rank"                # "which transfer type is slowest?"
    LIST = "list"                # "projects more than 30 days behind baseline"
    CLARIFY = "clarify"          # ambiguous -- ask rather than guess
    REFUSE = "refuse"            # out of scope or disallowed


class Aggregation(str, Enum):
    MEDIAN = "median"
    P25 = "p25"
    P75 = "p75"
    P90 = "p90"
    COUNT = "n"


class MetricQuery(BaseModel):
    intent: Intent
    metric_code: str | None = None
    aggregation: Aggregation = Aggregation.MEDIAN
    group_by: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    compare_to: dict[str, Any] | None = None
    threshold: int | None = None          # for LIST: "more than N days behind"

    # Populated when the question could mean several governed metrics. The agent
    # surfaces these instead of silently picking one -- "late" meaning baseline
    # deviation vs completion variance vs forecast error changes the answer.
    candidates: list[str] = Field(default_factory=list)
    question: str = ""
    reason: str = ""                       # why CLARIFY or REFUSE

    # Retrieved supporting documents. Explanatory only -- they never supply a
    # number, and never a metric definition, because both of those have exactly
    # one governed source. Retrieval widens what the assistant can *explain*,
    # never what it can assert.
    sources: list[dict] = Field(default_factory=list)

    def is_actionable(self) -> bool:
        return self.intent not in (Intent.CLARIFY, Intent.REFUSE)
