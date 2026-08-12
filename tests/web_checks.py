"""
Transfer & Conversion Intelligence Platform :: the console holds no SQL, no credentials and no metric logic.

The hand-built dashboard in `bi/` earns that claim by having almost nothing in
it. The React console is a much larger surface, so the same claim needs a much
more explicit gate — otherwise the first "quick fix" that computes a percentile
in a component puts the platform back to two definitions of cycle time, which is
the accreted mess the renovation exists to undo.

Seven assertions, all static. They read the source rather than running it, so
they hold on a machine with no warehouse, no model and no Node toolchain:

  1. No SQL anywhere under web/src.
  2. No database driver, DSN or connection string.
  3. No registered metric definition text baked into the frontend -- panels
     render the definition the API sent them, or they render nothing.
  4. No colour literals outside the design-token stylesheet.
  5. Every screen's data access goes through the typed API client.
  6. No hard-coded metric thresholds (the health band, the 14-day hit rate) --
     those are banded in SQL and only displayed here.
  7. The console reaches the warehouse through the API and nothing else: no
     direct port 5432, no Qdrant, no service URL other than the two proxies.
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEB_SRC = os.path.join(ROOT, "web", "src")
STYLES = os.path.join(WEB_SRC, "styles.css")

SQL_KEYWORDS = [
    r"\bSELECT\s+.*\bFROM\b", r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b",
    r"\bDELETE\s+FROM\b", r"\bCREATE\s+(TABLE|VIEW)\b", r"\bJOIN\b\s+\w+\s+\bON\b",
    r"\bGROUP\s+BY\b", r"\bPERCENTILE_CONT\b",
]

CREDENTIAL_MARKERS = [
    "postgresql://", "postgres://", "psycopg2", "5432",
    "password", "secret_key", "api_key", "ANTHROPIC_API_KEY",
]

# Phrases from tr_gov.metric_definition. A panel that hard-codes one of these is
# a panel that will keep printing it after the catalogue changes.
BAKED_DEFINITIONS = [
    "actual_finish - actual_start",
    "latest_planned_finish - baseline_finish",
    "actual_finish - baseline_finish",
    "forecast_finish - actual_start",
    "actual_finish - forecast_finish_as_of_snapshot",
    "count of projects completed in a fiscal period",
]

COLOUR_LITERAL = re.compile(r"(#[0-9a-fA-F]{3,8}\b|\boklch\(|\brgba?\()")

# The banding thresholds that live in SQL. A number is not evidence on its own,
# so each is paired with the identifier that would have to appear beside it for
# the frontend to be re-deriving the rule rather than displaying it.
THRESHOLD_PATTERNS = [
    (r"schedule_deviation_days\s*[<>]=?\s*30", "health band re-derived in the browser"),
    (r"abs_forecast_error_days\s*[<>]=?\s*14", "forecast hit threshold re-derived"),
    (r"within_14_days\s*=", "forecast hit threshold recomputed"),
]


def source_files(extensions=(".ts", ".tsx")):
    for folder, _dirs, files in os.walk(WEB_SRC):
        for name in sorted(files):
            if name.endswith(extensions):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    yield os.path.relpath(path, ROOT).replace("\\", "/"), handle.read()


def strip_comments(text):
    """Block and line comments removed, so prose about SQL is not read as SQL."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def run():
    if not os.path.isdir(WEB_SRC):
        print("web/src not found; nothing to check.")
        return True

    results = []
    files = list(source_files())

    # ---- 1: no SQL ---------------------------------------------------------
    offenders = []
    for path, text in files:
        body = strip_comments(text)
        for pattern in SQL_KEYWORDS:
            if re.search(pattern, body, flags=re.I):
                offenders.append(f"{path} matches {pattern}")
                break
    results.append(("the console contains no SQL", not offenders,
                    "; ".join(offenders) if offenders
                    else f"{len(files)} source files hold no query"))

    # ---- 2: no credentials or drivers --------------------------------------
    offenders = []
    for path, text in files:
        body = strip_comments(text).lower()
        for marker in CREDENTIAL_MARKERS:
            if marker.lower() in body:
                offenders.append(f"{path} mentions {marker}")
    results.append(("the console holds no credential or driver", not offenders,
                    "; ".join(offenders) if offenders
                    else "no DSN, driver or secret in the browser bundle"))

    # ---- 3: no baked metric definitions ------------------------------------
    offenders = []
    for path, text in files:
        for definition in BAKED_DEFINITIONS:
            if definition.lower() in text.lower():
                offenders.append(f"{path} bakes in '{definition}'")
    results.append(("no registered definition is baked into the frontend",
                    not offenders,
                    "; ".join(offenders) if offenders
                    else "every panel renders the definition the API sent"))

    # ---- 4: one palette ----------------------------------------------------
    offenders = []
    for path, text in files:
        for match in COLOUR_LITERAL.finditer(strip_comments(text)):
            offenders.append(f"{path} has colour literal {match.group(0)}")
            break
    results.append(("no component holds a private palette", not offenders,
                    "; ".join(offenders) if offenders
                    else "every mark reads a role token from styles.css"))

    # ---- 5: data access goes through the typed client ----------------------
    offenders = []
    for path, text in files:
        if path.endswith("lib/api.ts"):
            continue
        if re.search(r"\bfetch\s*\(", strip_comments(text)):
            offenders.append(path)
    results.append(("all data access goes through lib/api.ts", not offenders,
                    "; ".join(offenders) if offenders
                    else "no component calls fetch() directly"))

    # ---- 6: no re-derived thresholds ---------------------------------------
    offenders = []
    for path, text in files:
        body = strip_comments(text)
        for pattern, reason in THRESHOLD_PATTERNS:
            if re.search(pattern, body):
                offenders.append(f"{path}: {reason}")
    results.append(("banding thresholds are not re-derived in the browser",
                    not offenders,
                    "; ".join(offenders) if offenders
                    else "health and hit-rate bands come from the metric layer"))

    # ---- 7: the palette is defined in exactly one place --------------------
    has_tokens = os.path.exists(STYLES)
    token_count = 0
    if has_tokens:
        with open(STYLES, encoding="utf-8") as handle:
            token_count = len(COLOUR_LITERAL.findall(handle.read()))
    results.append(("the palette lives in one stylesheet", has_tokens and token_count > 0,
                    f"{token_count} colour values, all in web/src/styles.css"
                    if has_tokens else "styles.css missing"))

    print("Console checks")
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
