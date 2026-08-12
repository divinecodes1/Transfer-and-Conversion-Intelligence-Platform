"""
Transfer & Conversion Intelligence Platform :: BI layer checks.

How a chart looks is not what can silently go wrong here. What can is the BI
layer quietly acquiring its own opinion about a metric, a panel losing the
footnote that says which filters produced it, or the dashboard growing a route
to data that nobody reviewed.

So these drive `bi.server` -- the dashboard's whole server-side surface -- and
assert the properties the architecture actually rests on:

  * the dashboard reaches data only through the analytics API, and holds no
    driver, no connection string and no SQL anywhere in the package, static
    assets included;
  * the route list is closed: the browser cannot reach an arbitrary API path
    through the dashboard, so "BI consumes a governed contract" stays true;
  * every panel arrives with a complete provenance envelope, and the page reads
    exactly those fields, so each panel can state its own scope;
  * entitlements are inherited from the caller, never decided here.

Requires the PostgreSQL warehouse:
    make pg-up && make pg-build
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# These suites drive the demo identities (manager.auto, admin.demo) instead of
# standing up Keycloak, so they opt into demo mode explicitly. The platform
# default is enforce -- security is never opt-in -- and tests/security_checks.py
# asserts that default plus the fact that X-Demo-User is refused without it.
os.environ.setdefault("TRANSFEROPS_AUTH", "demo")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app as api_app  # noqa: E402
from bi.client import Api  # noqa: E402
from bi import server  # noqa: E402

BI_DIR = os.path.join(os.path.dirname(__file__), "..", "bi")
CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def dashboard(identity=None):
    """The dashboard server, wired to drive the API in-process."""
    api_client = TestClient(api_app)
    server.Api = lambda identity=None, **kw: Api(client=api_client, identity=identity)
    client = TestClient(server.app)
    if identity:
        client.headers.update({"X-Demo-User": identity})
    return client


def bi_sources():
    """Every file in the bi/ package, Python and static asset alike."""
    out = []
    for root, _dirs, files in os.walk(BI_DIR):
        if "__pycache__" in root:
            continue
        for f in sorted(files):
            if f.endswith((".py", ".js", ".css", ".html")):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, BI_DIR).replace(os.sep, "/")
                with open(path, encoding="utf-8") as fh:
                    out.append((rel, fh.read()))
    return out


PANELS = ["/api/cycle-time", "/api/schedule-drift", "/api/forecast",
          "/api/stage-cycle-time", "/api/portfolio"]

# The fields the footnote under every panel is built from.
ENVELOPE_FIELDS = ("metric_code", "definition", "population", "exclusions",
                   "version", "owner", "grain")


# ---------------------------------------------------------------------------
@check("the page and every panel source load through the dashboard server")
def _():
    c = dashboard()
    pages = {p: c.get(p) for p in ("/", "/healthz", "/static/app.css",
                                   "/static/app.js", "/static/charts.js")}
    broken = [p for p, r in pages.items() if r.status_code != 200 or not r.content]
    if broken:
        return False, f"broken: {broken}"
    panels = {p: c.get(p) for p in PANELS + ["/api/bootstrap", "/api/projects"]}
    empty = [p for p, r in panels.items() if r.status_code != 200 or not r.json()]
    return not empty, (f"empty: {empty}" if empty
                       else f"{len(pages)} assets + {len(panels)} panel sources, none empty")


@check("the BI package holds no database driver, credentials or SQL")
def _():
    # The structural guarantee behind "BI visualises, it never recomputes": if
    # nothing here can reach PostgreSQL, nothing here can invent a metric.
    # Static assets are scanned too -- a fetch() in JS is as much a data path as
    # a cursor in Python.
    forbidden = ("psycopg2", "duckdb", "sqlalchemy", "postgresql://", "postgres://")
    executable_sql = re.compile(r"\bselect\b[\s\S]{0,150}?\bfrom\s+tr_", re.IGNORECASE)
    offenders = []
    for name, text in bi_sources():
        for needle in forbidden:
            if needle in text.lower():
                offenders.append(f"{name}:{needle}")
        if executable_sql.search(text):
            offenders.append(f"{name}:SQL")
    return not offenders, ("; ".join(offenders) or
                           f"{len(bi_sources())} files in bi/, no db access, no SQL")


@check("the route list is closed -- the browser cannot reach arbitrary API paths")
def _():
    # A transparent /api/{path} proxy would make the dashboard an unreviewed
    # second client of the warehouse. These paths exist on the analytics API and
    # must NOT be reachable through the dashboard.
    c = dashboard()
    leaked = [p for p in ("/api/catalogue", "/api/metrics/cycle-time",
                          "/api/whoami", "/api/observability/metrics")
              if c.get(p).status_code == 200]
    return not leaked, (f"reachable through the dashboard: {leaked}" if leaked
                        else "only the named panel routes are served")


@check("AI product routes stay governed, explainable and identity-aware")
def _():
    c = dashboard("manager.auto")
    filters = {"filters": {"portfolio": "PF_AUTO"}}
    insight = c.post("/api/insight", json=filters)
    risks = c.post("/api/project-risks", json=filters)
    draft = c.post("/api/report-draft", json={
        **filters, "audience": "steering_committee", "cadence": "weekly"})
    answer = c.post("/api/ask", json={
        "question": "Which transfer type has the highest cycle time?"})
    if any(r.status_code != 200 for r in (insight, risks, draft, answer)):
        return False, ", ".join(str(r.status_code)
                                for r in (insight, risks, draft, answer))
    ib, rb, db, ab = (r.json() for r in (insight, risks, draft, answer))
    ok = bool(
        ib.get("provenance")
        and ib.get("filters_applied") == {"portfolio": "PF_AUTO"}
        and all("drivers" in row for row in rb.get("risks", []))
        and db.get("provenance")
        and ab.get("provenance_complete")
        and ab.get("tool_called")
    )
    return ok, ("briefing, risk, email and Ask AI all expose evidence"
                if ok else "one or more AI responses lacks scope or provenance")


@check("the product shell exposes the complete reference workflow set")
def _():
    sources = dict(bi_sources())
    html = sources["static/index.html"]
    js = sources["static/app.js"]
    expected = ("Portfolio", "Projects", "Analytics", "Reports", "Ask AI",
                "Operations", "AI portfolio briefing", "Project register",
                "Data import", "Connections", "AI automation", "Access control")
    missing = [label for label in expected if label not in html + js]
    return not missing, (f"all {len(expected)} workflows are present"
                         if not missing else f"missing: {missing}")


@check("AI automation history is restricted to platform administrators")
def _():
    manager = dashboard("manager.auto").get("/api/assistant-audit")
    admin = dashboard("admin.demo").get("/api/assistant-audit")
    return (manager.status_code == 403 and admin.status_code == 200,
            f"manager={manager.status_code}, admin={admin.status_code}")


@check("every metric panel arrives with a complete provenance envelope")
def _():
    c = dashboard()
    for path in PANELS:
        body = c.get(path).json()
        metrics = body.get("metrics") or []
        if not metrics:
            return False, f"{path}: no metric definitions attached"
        for m in metrics:
            missing = [f for f in ENVELOPE_FIELDS if not m.get(f)]
            if missing:
                return False, f"{path}: {m.get('metric_code')} missing {missing}"
        if "data_as_of" not in body or "filters_applied" not in body:
            return False, f"{path}: no vintage or filters"
    return True, f"{len(PANELS)} panels carry definition, population, version and vintage"


@check("the page renders the envelope rather than restating a definition")
def _():
    # The footnote is the "self-explaining" claim made visible. It has to be
    # built from the envelope the API sent -- a definition hard-coded in the
    # frontend would be a second source of truth for what a metric means.
    app_js = dict(bi_sources())["static/app.js"]
    reads = [f for f in ("metrics", "definition", "population", "exclusions",
                         "version", "owner", "filters_applied", "data_as_of")
             if f in app_js]
    # No registered definition text may be baked into the page.
    c = dashboard()
    defs = [m["definition"] for m in c.get("/api/bootstrap").json()["catalogue"]]
    baked = [d for d in defs if d in app_js]
    return (len(reads) == 8 and not baked,
            f"baked-in definitions: {baked}" if baked
            else f"reads all {len(reads)} envelope fields, hard-codes no definition")


@check("box-plot series carries the quartiles the chart needs")
def _():
    rows = [r for r in dashboard().get(
        "/api/cycle-time", params={"group_by": "fiscal_year"}).json()["series"]
        if r["group_value"] is not None]
    need = ("p25", "median", "p75", "p90", "min_days", "n")
    missing = [f for r in rows for f in need if r.get(f) is None]
    return (bool(rows) and not missing,
            f"{len(rows)} fiscal years, all with min/p25/median/p75/p90")


@check("the dashboard inherits the viewer's entitlements, it never decides them")
def _():
    mgr = dashboard("manager.auto").get("/api/portfolio").json()["series"]
    admin = dashboard("admin.demo").get("/api/portfolio").json()["series"]
    seen = {r["portfolio"] for r in mgr}
    # And the identity the page displays is the one the API resolved.
    who = dashboard("manager.auto").get("/api/bootstrap").json()["whoami"]
    return (seen == {"PF_AUTO"} and len(admin) > len(mgr)
            and who["username"] == "manager.auto" and not who["unrestricted"],
            f"manager sees {sorted(seen)} ({len(mgr)} rows), admin {len(admin)} rows")


def run():
    print("BI layer checks")
    print("-" * 72)
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
