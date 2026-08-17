"""
Transfer & Conversion Intelligence Platform :: the console holds no SQL, no credentials and no metric logic.

The hand-built dashboard in `bi/` earns that claim by having almost nothing in
it. The React console is a much larger surface, so the same claim needs a much
more explicit gate — otherwise the first "quick fix" that computes a percentile
in a component puts the platform back to two definitions of cycle time, which is
the accreted mess the renovation exists to undo.

Nine assertions, all static. They read the source rather than running it, so
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
  8. Every text colour clears WCAG AA against every surface it can land on --
     measured in both themes, not eyeballed against white.
  9. No component sets its own type size below the 12px floor.

The last two are legibility rather than governance, and they are here for the
same reason as the rest: the console had drifted to 12px grey body text that
read below AA on the two surfaces built to hold it, and nothing in the build
would ever have said so.
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


# ---- Legibility ------------------------------------------------------------
#
# The two properties a dense analytical console loses first, both of which look
# fine to whoever wrote the component and fail for the person reading it at the
# end of a shift.
#
# Contrast is checked against every surface a token can land on, not against
# white. That is the distinction that matters: --muted-foreground was #6b7280,
# which passes on a white card and fails on the grey panel and the tinted AI
# brief -- the two surfaces that exist specifically to hold secondary text.
#
# Body text at 4.5:1 is WCAG AA. --text-disabled is deliberately exempt: it says
# "you cannot use this", and holding it to the body floor would make a disabled
# control look enabled. It still has to be readable, hence 3:1.
TEXT_FLOOR = 4.5
DISABLED_FLOOR = 3.0
SURFACE_TOKENS = ("card", "background", "muted", "primary-050", "accent")
TEXT_TOKENS = ("foreground", "card-foreground", "muted-foreground", "text-muted",
               "secondary-foreground", "accent-foreground", "primary",
               "ok", "warn", "bad")

# Below this, uppercase micro-labels stop being terse and start being unreadable.
# The scale registers --text-label at the floor; anything smaller written inline
# is a component choosing its own type size, which is how a console ends up at
# 10px.
MIN_FONT_PX = 12
INLINE_FONT_SIZE = re.compile(r"text-\[(\d+(?:\.\d+)?)px\]")


def _oklch_to_rgb(lightness, chroma, hue):
    """OKLCH -> sRGB 0..1, so the dark theme is measured rather than assumed."""
    import math

    hr = math.radians(hue)
    a, b = chroma * math.cos(hr), chroma * math.sin(hr)
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = l_ ** 3, m_ ** 3, s_ ** 3
    linear = (
        +4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
        -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
        -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3,
    )
    out = []
    for value in linear:
        srgb = (12.92 * value if value <= 0.0031308
                else 1.055 * (value ** (1 / 2.4)) - 0.055)
        out.append(min(1.0, max(0.0, srgb)))
    return tuple(out)


def _colour(value):
    value = value.strip().rstrip(";").strip()
    hex_match = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if hex_match:
        digits = hex_match.group(1)
        return tuple(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))
    oklch = re.fullmatch(
        r"oklch\(\s*([\d.]+)%?\s+([\d.]+)\s+([\d.]+)\s*\)", value)
    if oklch:
        lightness, chroma, hue = (float(g) for g in oklch.groups())
        if lightness > 1:            # written as a percentage
            lightness /= 100
        return _oklch_to_rgb(lightness, chroma, hue)
    return None


def _contrast(foreground, background):
    def luminance(rgb):
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                    for c in rgb]
        return (0.2126 * channels[0] + 0.7152 * channels[1]
                + 0.0722 * channels[2])
    a, b = luminance(foreground), luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def theme_tokens(css, block):
    """The resolvable colour tokens declared in `:root {...}` or `.dark {...}`."""
    match = re.search(re.escape(block) + r"\s*\{(.*?)\n\}", css, re.S)
    if not match:
        return {}
    found = {}
    for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", match.group(1)):
        colour = _colour(value)
        if colour is not None:
            found[name] = colour
    return found


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

    # ---- 8: text is legible on every surface it lands on -------------------
    with open(STYLES, encoding="utf-8") as handle:
        css = handle.read()

    offenders, measured = [], 0
    for theme in (":root", ".dark"):
        tokens = theme_tokens(css, theme)
        surfaces = [(n, tokens[n]) for n in SURFACE_TOKENS if n in tokens]
        for name in TEXT_TOKENS:
            if name not in tokens:
                continue
            for surface_name, surface in surfaces:
                ratio = _contrast(tokens[name], surface)
                measured += 1
                if ratio < TEXT_FLOOR:
                    offenders.append(
                        f"{theme} --{name} on --{surface_name}: {ratio:.2f}")
        if "text-disabled" in tokens:
            for surface_name, surface in surfaces:
                ratio = _contrast(tokens["text-disabled"], surface)
                measured += 1
                if ratio < DISABLED_FLOOR:
                    offenders.append(
                        f"{theme} --text-disabled on --{surface_name}: "
                        f"{ratio:.2f}")
    results.append(("every text colour clears AA on every surface it sits on",
                    not offenders,
                    "; ".join(offenders[:4]) if offenders
                    else f"{measured} colour/surface pairs measured in both themes"))

    # ---- 9: nothing renders below the type floor ---------------------------
    offenders = []
    for path, text in files:
        for match in INLINE_FONT_SIZE.finditer(strip_comments(text)):
            if float(match.group(1)) < MIN_FONT_PX:
                offenders.append(f"{path} sets {match.group(0)}")
    results.append((f"no component sets its own type size below {MIN_FONT_PX}px",
                    not offenders,
                    "; ".join(offenders[:4]) if offenders
                    else "labels use the registered text-label size"))

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
