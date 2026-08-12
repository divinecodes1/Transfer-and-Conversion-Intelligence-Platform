"""Governed narrative and risk helpers for the Transfer & Conversion Intelligence Platform product UI.

These helpers turn API responses into decision support. They never query the
warehouse directly and never redefine a registered metric. The deterministic
fallback is intentional: briefings remain available when no external model is
configured, and every number can still be traced to a governed endpoint.
"""
from datetime import datetime, timezone


def _filters(filters):
    return {key: value for key, value in (filters or {}).items()
            if value not in (None, "")}


def _scope(filters):
    clean = _filters(filters)
    if not clean:
        return "the whole visible portfolio"
    return ", ".join(f"{key.replace('_', ' ')} {value}"
                     for key, value in clean.items())


def _project_filters(filters):
    return {key: value for key, value in _filters(filters).items()
            if key in {"portfolio", "transfer_type", "health"}}


def _portfolio_filters(filters):
    return {key: value for key, value in _filters(filters).items()
            if key in {"fiscal_year", "portfolio"}}


def _forecast_filters(filters):
    return {key: value for key, value in _filters(filters).items()
            if key in {"portfolio", "transfer_type"}}


def _risk(project):
    deviation = project.get("schedule_deviation_days") or 0
    health = project.get("health") or "UNKNOWN"
    complexity = (project.get("complexity_class") or "").upper()
    score = {"ON_TRACK": 18, "AT_RISK": 52, "LATE": 76,
             "UNKNOWN": 34}.get(health, 34)
    score += min(max(deviation, 0), 90) * 0.22
    if complexity in {"HIGH", "VERY_HIGH", "COMPLEX"}:
        score += 8
    score = max(0, min(100, round(score)))
    band = "critical" if score >= 75 else "high" if score >= 55 else \
        "medium" if score >= 30 else "low"
    predicted = max(0, round(deviation * 1.15))
    drivers = []
    if deviation > 30:
        drivers.append(f"{round(deviation)} days beyond baseline")
    elif deviation > 0:
        drivers.append(f"{round(deviation)} days of schedule drift")
    if complexity in {"HIGH", "VERY_HIGH", "COMPLEX"}:
        drivers.append("high delivery complexity")
    if health == "UNKNOWN":
        drivers.append("incomplete schedule signal")
    if not drivers:
        drivers.append("current schedule remains within baseline")
    return {
        "project_id": project.get("project_id"),
        "risk_score": score,
        "risk_band": band,
        "predicted_slip_days": predicted,
        "drivers": drivers,
        "rationale": ("Risk is estimated from governed schedule drift, current "
                      "health, and delivery complexity."),
    }


def project_risks(api, filters=None, limit=500):
    if hasattr(api, "register"):
        payload = api.register(limit=limit, **_filters(filters))
        projects = [row for row in payload.get("projects", [])
                    if row.get("status") in {"ACTIVE", "PLANNED"}]
    else:
        payload = api.projects(limit=limit, **_project_filters(filters))
        projects = payload.get("projects", [])
    rows = [_risk(project) for project in projects]
    return {
        "risks": rows,
        "total_matching": len(rows),
        "data_as_of": payload.get("data_as_of"),
        "method": "governed-risk-v1",
    }


def portfolio_briefing(api, filters=None):
    filters = _filters(filters)
    if hasattr(api, "register"):
        projects = api.register(limit=1000, **filters)
        active = [row for row in projects.get("projects", [])
                  if row.get("status") in {"ACTIVE", "PLANNED"}]
        kpis = api.kpis(**filters).get("kpis", {})
        completed = kpis.get("throughput") or 0
        on_time = kpis.get("on_time_rate")
        forecast = api.accuracy(**{
            key: value for key, value in filters.items()
            if key != "fiscal_year"})
        provenance = ["GET /mart/projects", "GET /mart/kpis",
                      "GET /mart/accuracy"]
    else:
        projects = api.projects(limit=1000, **_project_filters(filters))
        active = projects.get("projects", [])
        portfolio = api.portfolio(**_portfolio_filters(filters))
        completed = sum((row.get("throughput") or 0)
                        for row in portfolio.get("series", []))
        weighted = sum((row.get("on_time_rate") or 0) *
                       (row.get("throughput") or 0)
                       for row in portfolio.get("series", []))
        on_time = (weighted / completed * 100) if completed else None
        forecast = api.forecast(**_forecast_filters(filters))
        provenance = ["GET /projects", "GET /metrics/portfolio",
                      "GET /metrics/forecast"]
    late = [row for row in active if row.get("health") == "LATE"]
    at_risk = [row for row in active if row.get("health") == "AT_RISK"]
    horizon = next((row for row in forecast.get("series", [])
                    if row.get("horizon_bucket") == "90+"), None)
    worst = sorted(late + at_risk,
                   key=lambda row: row.get("schedule_deviation_days") or 0,
                   reverse=True)[:3]
    if late:
        headline = f"{len(late)} open transfers need leadership attention"
    elif at_risk:
        headline = f"{len(at_risk)} transfers are approaching their baseline"
    else:
        headline = "The open portfolio is currently within tolerance"
    on_time_text = f"{on_time:.1f}%" if on_time is not None else "not available"
    forecast_text = (f"{horizon.get('median_abs_error'):.0f} days"
                     if horizon and horizon.get("median_abs_error") is not None
                     else "not available")
    content = (
        f"Across {_scope(filters)}, {len(active)} transfers are open: "
        f"{len(late)} late and {len(at_risk)} at risk. On-time completion is "
        f"{on_time_text} across {completed} completed transfers. The median "
        f"absolute error for forecasts made 90 or more days out is "
        f"{forecast_text}."
    )
    highlights = [
        {"label": "Open transfers", "value": len(active), "tone": "neutral"},
        {"label": "Late", "value": len(late), "tone": "critical" if late else "good"},
        {"label": "At risk", "value": len(at_risk), "tone": "warning" if at_risk else "good"},
        {"label": "On time", "value": on_time_text, "tone": "good" if on_time and on_time >= 75 else "warning"},
    ]
    return {
        "kind": "portfolio_briefing",
        "headline": headline,
        "content": content,
        "highlights": highlights,
        "attention": [_risk(row) for row in worst],
        "filters_applied": filters,
        "data_as_of": projects.get("data_as_of"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "governed-insight-engine-v1",
        "provenance": provenance,
    }


def draft_report(api, filters=None, audience="steering_committee", cadence="weekly"):
    insight = portfolio_briefing(api, filters)
    audience_name = {
        "steering_committee": "Steering Committee",
        "site_leads": "Site Leads",
        "project_managers": "Project Managers",
    }.get(audience, "Steering Committee")
    attention = insight["attention"]
    lines = [
        f"{cadence.title()} Transfer & Conversion Intelligence Platform update for {audience_name}",
        "",
        insight["content"],
        "",
        "Key numbers",
    ]
    lines.extend(f"- {item['label']}: {item['value']}"
                 for item in insight["highlights"])
    lines.extend(["", "Attention required"])
    if attention:
        lines.extend(
            f"- {row['project_id']}: {row['risk_band']} risk; "
            f"{', '.join(row['drivers'])}." for row in attention)
    else:
        lines.append("- No open transfer currently exceeds the late threshold.")
    lines.extend(["", "Recommended actions",
                  "- Confirm owners and next recovery dates for every late transfer.",
                  "- Review long-horizon forecasts before the next governance meeting."])
    return {
        "subject": f"Transfer & Conversion Intelligence Platform: {insight['headline']}",
        "body": "\n".join(lines),
        "generated_at": insight["generated_at"],
        "filters_applied": insight["filters_applied"],
        "provenance": insight["provenance"],
    }
