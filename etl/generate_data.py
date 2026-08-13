"""
Transfer & Conversion Intelligence Platform :: synthetic transfer-portfolio generator.

Produces a realistic portfolio of semiconductor product/technology *transfer*
projects and, crucially, the HISTORY needed to compute the metrics correctly:
  - dim_project            : identity + actuals
  - dim_milestone          : the 6-stage transfer lifecycle
  - fact_milestone_event   : planned vs actual per milestone
  - fact_schedule_revision : immutable baseline + replans  (original vs latest)
  - fact_project_snapshot  : monthly point-in-time forecasts (forecast accuracy)
  - dim_fiscal_date        : Infineon fiscal calendar (FY starts 1 October)

Writes one CSV per table into ./data. Deterministic (fixed seed) so the
golden-project reconciliation tests are stable.

Golden project T-017 is injected with exact values so the numbers in the
architecture doc can be asserted:
    start 2026-01-10, baseline finish 2026-04-10, latest finish 2026-05-05,
    actual finish 2026-05-08  ->  cycle 118, deviation +25, variance +28, on-time No.
"""
import csv, os, random, datetime as dt

SEED = 42
N_PROJECTS = 260
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
random.seed(SEED)

TRANSFER_TYPES = ["FAB_TO_FAB", "INT_TO_FOUNDRY", "FOUNDRY_TO_INT", "ASSY_MOVE", "NODE_CONVERSION"]
COMPLEXITY     = ["LOW", "MED", "HIGH"]
SITES          = ["Villach", "Dresden", "Regensburg", "Kulim", "Batam", "Melaka", "Wuxi", "Dublin"]
PORTFOLIOS     = ["PF_AUTO", "PF_POWER", "PF_IOT"]        # Automotive / Green Power / Connected Secure
STATUSES       = ["COMPLETED", "ACTIVE", "PLANNED", "CANCELLED"]
STATUS_WEIGHTS = [0.55, 0.30, 0.10, 0.05]

# Base full-transfer duration (days) by complexity.
BASE_DURATION = {"LOW": 180, "MED": 300, "HIGH": 470}

# Cumulative fraction of total duration at which each milestone lands.
MILESTONES = [
    ("DESIGN_TRANSFER", "Design Transfer", 1, 0.12),
    ("TAPEOUT",         "Tapeout",          2, 0.30),
    ("QUAL_LOTS",       "Qualification Lots", 3, 0.52),
    ("REL_QUAL",        "Reliability Qual", 4, 0.70),
    ("CUST_QUAL",       "Customer Qual",    5, 0.86),
    ("PROD_RELEASE",    "Production Release", 6, 1.00),
]

TODAY = dt.date(2026, 8, 11)   # "as of" date used for active projects

# ---- Readiness ------------------------------------------------------------
# The seven dimensions and their weights. These are written to
# dim_readiness_dimension and the calculation layer reads them from there --
# this list is the seed, not the rule.
#
# Note on the master plan: §13 lists these weights AND an example scoring
# (product 100, process 91, equipment 67, material 86, qualification 61,
# target site 73, documentation 96) that it labels "78%". Those inputs against
# these weights give 77.15%, not 78%. The weights are implemented as the plan
# states them and the score is whatever they produce; the golden vector below
# preserves the plan's example so the arithmetic is inspectable rather than
# quietly adjusted to match the prose.
READINESS_DIMENSIONS = [
    ("QUALIFICATION", "Qualification Readiness", 25, 1),
    ("EQUIPMENT",     "Equipment Readiness",     20, 2),
    ("PROCESS",       "Process Readiness",       15, 3),
    ("TARGET_SITE",   "Target Site Readiness",   15, 4),
    ("PRODUCT",       "Product Readiness",       10, 5),
    ("DOCUMENTATION", "Documentation Readiness", 10, 6),
    ("MATERIAL",      "Material Readiness",       5, 7),
]

# How strongly each dimension responds to a project that is running long.
# Qualification and equipment carry most of the signal, which is what makes the
# root-cause reading ("qualification is the bottleneck") fall out of the data
# rather than being asserted over it.
READINESS_SENSITIVITY = {
    "QUALIFICATION": 1.00, "EQUIPMENT": 0.85, "TARGET_SITE": 0.55,
    "PROCESS": 0.50, "MATERIAL": 0.35, "PRODUCT": 0.25, "DOCUMENTATION": 0.20,
}

# The master plan's §13 worked example, preserved exactly.
GOLDEN_READINESS = {
    "PRODUCT": 100, "PROCESS": 91, "EQUIPMENT": 67, "MATERIAL": 86,
    "QUALIFICATION": 61, "TARGET_SITE": 73, "DOCUMENTATION": 96,
}


def d(base: dt.date, days: float) -> dt.date:
    return base + dt.timedelta(days=round(days))


# The gaps between the cumulative MILESTONES fractions, i.e. how much of a
# transfer each stage consumes in the nominal plan.
STAGE_GAPS = [0.12, 0.18, 0.22, 0.18, 0.16, 0.14]


def stage_fracs(pk: int):
    """
    Per-project cumulative milestone fractions.

    Every project used to place its milestones at exactly the same fractions, and
    the consequence only became visible once the lane view asked which stage costs
    a route the most time: TAPEOUT -> QUAL_LOTS is the widest nominal gap, so it
    was the answer for every lane, every time. A "bottleneck" column that reads
    the same value in all forty rows is the REPLAN_RATE-at-100% failure again -- a
    constant wearing a chart's clothes, and one that hides the metric's own bugs
    behind it.

    Giving each project its own stage weights makes the bottleneck a finding.
    Seeded off the project key from a private stream, so it is deterministic and
    the main generator's draws are untouched.
    """
    if pk == 17:
        # The golden project keeps the documented geometry exactly.
        return [frac for _c, _n, _s, frac in MILESTONES]
    rng = random.Random(9000 + pk)
    weights = [max(0.04, gap * rng.uniform(0.45, 1.9)) for gap in STAGE_GAPS]
    total = sum(weights)
    out, acc = [], 0.0
    for w in weights:
        acc += w / total
        out.append(round(acc, 4))
    out[-1] = 1.0          # the last milestone is completion, by definition
    return out


def slip_factor(complexity: str) -> float:
    """Multiplier on baseline duration. Right-skewed for HIGH complexity."""
    base = random.gauss(1.06, 0.16)
    if complexity == "HIGH" and random.random() < 0.35:
        base += random.uniform(0.15, 0.6)          # heavy tail: some big overruns
    if complexity == "LOW" and random.random() < 0.25:
        base -= random.uniform(0.05, 0.15)          # a few early finishers
    return max(0.55, base)


def make_project(i: int):
    pk = i
    pid = f"T-{i:03d}"
    ttype = random.choice(TRANSFER_TYPES)
    cx = random.choices(COMPLEXITY, weights=[0.4, 0.4, 0.2])[0]
    src, tgt = random.sample(SITES, 2)
    pf = random.choice(PORTFOLIOS)
    status = random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]

    base_dur = BASE_DURATION[cx] * random.uniform(0.9, 1.1)
    # Spread starts across ~ FY23..FY26
    start = dt.date(2022, 10, 1) + dt.timedelta(days=random.randint(0, 1200))

    baseline_finish = d(start, base_dur)
    slip = slip_factor(cx)
    actual_dur = base_dur * slip
    projected_finish = d(start, actual_dur)

    # Resolve actuals by status
    if status == "COMPLETED":
        actual_start, actual_finish = start, projected_finish
        if actual_finish > TODAY:                   # can't complete in the future
            actual_finish = d(start, min(actual_dur, (TODAY - start).days - 5))
    elif status == "ACTIVE":
        actual_start, actual_finish = start, None
        if start > TODAY:                           # started in future -> make it recent
            actual_start = TODAY - dt.timedelta(days=random.randint(30, 200))
    elif status == "PLANNED":
        actual_start, actual_finish = None, None
        start = TODAY + dt.timedelta(days=random.randint(10, 180))   # future baseline
        baseline_finish = d(start, base_dur)
        projected_finish = baseline_finish
    else:  # CANCELLED
        actual_start = start if random.random() < 0.7 else None
        actual_finish = None

    return {
        "project_key": pk, "project_id": pid, "project_name": f"{ttype} {src}->{tgt}",
        "transfer_type": ttype, "complexity_class": cx, "source_site": src,
        "target_site": tgt, "portfolio": pf, "status": status,
        "actual_start": actual_start, "actual_finish": actual_finish,
        # carried internally for building history:
        "_start": start, "_baseline_finish": baseline_finish,
        "_projected_finish": projected_finish, "_base_dur": base_dur,
        "_slip": slip,
    }


def build_history(proj):
    """Return (revisions, snapshots, milestone_events) for one project."""
    pk = proj["project_key"]
    start = proj["_start"]
    base_fin = proj["_baseline_finish"]
    proj_fin = proj["_projected_finish"]
    status = proj["status"]

    # ---- schedule revisions: baseline + drift toward the eventual/forecast finish
    revisions = []
    revisions.append({
        "project_key": pk, "revision_id": 0,
        "revision_timestamp": dt.datetime.combine(start, dt.time(9, 0)),
        "revision_reason": "BASELINE", "planned_start": start,
        "planned_finish": base_fin, "forecast_finish": base_fin, "is_baseline": True,
    })
    n_rev = random.randint(1, 4)
    # One project in five is never replanned: it runs to its original commitment.
    #
    # Without this every project carries at least one replan, and REPLAN_RATE --
    # a headline KPI -- reads a flat 100%, which tells a reader nothing and hides
    # the metric's own bugs behind a constant. The decision is a function of the
    # project key rather than another random draw, so the generator's random
    # stream is unchanged and the hand-agreed T-017 expectations still hold; the
    # draw above is still made and discarded for exactly that reason.
    if pk % 5 == 3:
        n_rev = 0
    end_ref = proj_fin if status in ("COMPLETED", "ACTIVE") else base_fin
    for r in range(1, n_rev + 1):
        frac = r / (n_rev + 1)
        rev_ts = dt.datetime.combine(d(start, proj["_base_dur"] * frac), dt.time(9, 0))
        # planned finish converges from baseline toward end_ref
        pf_days = (base_fin - start).days + frac * ((end_ref - start).days - (base_fin - start).days)
        planned_fin = d(start, pf_days)
        revisions.append({
            "project_key": pk, "revision_id": r,
            "revision_timestamp": rev_ts,
            "revision_reason": random.choice(["REPLAN", "SCOPE_CHANGE", "RESOURCE", "SUPPLIER_DELAY"]),
            "planned_start": start, "planned_finish": planned_fin,
            "forecast_finish": planned_fin, "is_baseline": False,
        })

    # ---- monthly snapshots: forecast converges to actual as completion nears
    snapshots = []
    if status in ("COMPLETED", "ACTIVE") and proj["actual_start"]:
        s0 = proj["actual_start"]
        end = proj["actual_finish"] or TODAY
        cur = dt.date(s0.year, s0.month, 1)
        while cur <= end:
            elapsed = max(0.0, (cur - s0).days)
            total = max(1.0, (proj_fin - s0).days)
            prog = min(1.0, elapsed / total)
            # forecast interpolates baseline_finish -> projected_finish as progress grows
            fdays = (base_fin - s0).days + prog * ((proj_fin - s0).days - (base_fin - s0).days)
            snapshots.append({
                "project_key": pk, "snapshot_date": cur,
                "status": status,
                "forecast_finish": d(s0, fdays),
                "current_stage": MILESTONES[min(5, int(prog * 6))][0],
                "risk_status": "RED" if prog < 0.9 and (proj_fin - base_fin).days > 45
                               else ("AMBER" if (proj_fin - base_fin).days > 15 else "GREEN"),
                "progress_pct": round(prog * 100, 1),
            })
            # advance one month
            y, m = (cur.year + (cur.month // 12), (cur.month % 12) + 1)
            cur = dt.date(y, m, 1)

    # ---- milestone events (planned from baseline, actual from realised schedule)
    # Plan and actual share the project's stage shape: a project whose
    # qualification stage is long planned for it being long. Using the nominal
    # fractions for the plan and the project's own for the actual would make every
    # project appear to miss its interior milestones by construction.
    events = []
    fracs = stage_fracs(pk)
    for (code, name, seq, _nominal), frac in zip(MILESTONES, fracs):
        planned = d(start, proj["_base_dur"] * frac)
        actual = None
        estatus = "PLANNED"
        if proj["actual_start"]:
            realised = d(proj["actual_start"], proj["_base_dur"] * (proj_fin - start).days
                         / max(1, proj["_base_dur"]) * frac)
            reached_by = proj["actual_finish"] or TODAY
            if realised <= reached_by and status != "PLANNED":
                actual, estatus = realised, "REACHED"
        events.append({
            "project_key": pk, "milestone_key": seq,
            "planned_date": planned, "actual_date": actual, "event_status": estatus,
        })
    return revisions, snapshots, events


def build_readiness(projects, rng, vintage):
    """
    One readiness row per in-flight project per dimension.

    Population is deliberate: readiness answers "how prepared is this transfer to
    execute?", which is a question about work still ahead. A COMPLETED project has
    an outcome, not a readiness, and scoring one would put a 100% row into every
    portfolio average and drag the number toward "fine" exactly as the active work
    got harder. CANCELLED is excluded for the same reason every other metric
    excludes it.

    Scores are driven by the project's own slip factor rather than drawn freely,
    so readiness and schedule outcome are correlated the way they are in reality
    -- otherwise the readiness screen is a random-number generator that happens to
    render as a bar chart, and every insight built on it is an artefact.

    `rng` is a private stream. The existing generator's draws are untouched, so
    dim_project and every history table stay byte-identical and the golden gate
    keeps asserting the same numbers it always did.

    `vintage` is the newest project snapshot, i.e. what the warehouse will report
    as `data_as_of`, and assessments are dated backwards from it rather than from
    TODAY. Anchoring to the wall clock instead produced assessments dated *after*
    the data vintage and an average assessment age of MINUS seven days -- a
    readiness score the warehouse could not yet have known about. Everything
    time-relative in this platform is measured against the vintage for exactly
    this reason.
    """
    rows = []
    golden_key = None
    for p in sorted(projects, key=lambda x: x["project_key"]):
        if p["status"] not in ("ACTIVE", "PLANNED"):
            continue
        # Work already banked. A project that has not started is less ready than
        # one halfway through, independently of how well it is going.
        maturity = 1.0 if p["status"] == "ACTIVE" else 0.55
        # How badly it is running long, 0 (on plan) .. 1 (heavy overrun).
        pressure = min(1.0, max(0.0, p["_slip"] - 1.0))

        if golden_key is None and p["status"] == "ACTIVE":
            golden_key = p["project_key"]
            scores = dict(GOLDEN_READINESS)
        else:
            scores = {}
            for code, _name, _w, _seq in READINESS_DIMENSIONS:
                drop = pressure * READINESS_SENSITIVITY[code] * 90.0
                raw = 100.0 - drop - (1.0 - maturity) * 30.0 + rng.gauss(0, 6)
                scores[code] = int(round(min(100.0, max(0.0, raw))))

        for code, _name, _w, _seq in READINESS_DIMENSIONS:
            # Most assessments are current; a tail is stale, which is what makes
            # "when was this last looked at?" a question worth putting on screen.
            age = rng.randint(0, 21) if rng.random() < 0.85 else rng.randint(22, 120)
            rows.append({
                "project_key": p["project_key"],
                "dimension_code": code,
                "assessed_on": vintage - dt.timedelta(days=age),
                "score_pct": scores[code],
            })
    return rows, golden_key


def inject_golden(projects):
    """Force project index 17 to the doc's exact golden values (T-017)."""
    for p in projects:
        if p["project_id"] == "T-017":
            p["status"] = "COMPLETED"
            p["transfer_type"] = "FAB_TO_FAB"
            p["complexity_class"] = "MED"
            p["_start"] = dt.date(2026, 1, 10)
            p["actual_start"] = dt.date(2026, 1, 10)
            p["_baseline_finish"] = dt.date(2026, 4, 10)
            p["_projected_finish"] = dt.date(2026, 5, 8)
            p["actual_finish"] = dt.date(2026, 5, 8)
            p["_base_dur"] = (dt.date(2026, 4, 10) - dt.date(2026, 1, 10)).days
            # force latest revision to 2026-05-05 exactly
            p["_force_latest_finish"] = dt.date(2026, 5, 5)
            return p
    return None


def fiscal_row(cal: dt.date):
    fy = cal.year + 1 if cal.month >= 10 else cal.year          # Infineon FY starts Oct
    fmonth = (cal.month - 10) % 12 + 1
    fq = (fmonth - 1) // 3 + 1
    fweek = cal.isocalendar()[1]
    return {"calendar_date": cal, "fiscal_week": fweek, "fiscal_month": fmonth,
            "fiscal_quarter": fq, "fiscal_year": fy}


def write_csv(name, rows, cols):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})


def main():
    os.makedirs(OUT, exist_ok=True)
    projects = [make_project(i) for i in range(1, N_PROJECTS + 1)]
    golden = inject_golden(projects)

    revisions, snapshots, events = [], [], []
    all_dates = set()
    for p in projects:
        revs, snaps, evs = build_history(p)
        # apply golden override for latest revision finish
        if p.get("_force_latest_finish"):
            revs[-1]["planned_finish"] = p["_force_latest_finish"]
            revs[-1]["forecast_finish"] = p["_force_latest_finish"]
            revs[-1]["revision_reason"] = "REPLAN"
        revisions += revs; snapshots += snaps; events += evs
        for x in (p["actual_start"], p["actual_finish"], p["_baseline_finish"]):
            if x: all_dates.add(x)

    # fiscal calendar spanning everything
    lo = min(all_dates); hi = max(all_dates)
    cal = dt.date(lo.year, 1, 1); end = dt.date(hi.year, 12, 31)
    fiscal = []
    while cal <= end:
        fiscal.append(fiscal_row(cal)); cal += dt.timedelta(days=1)

    # write tables
    write_csv("dim_project.csv", projects,
              ["project_key","project_id","project_name","transfer_type","complexity_class",
               "source_site","target_site","portfolio","status","actual_start","actual_finish"])
    write_csv("dim_milestone.csv",
              [{"milestone_key": s, "milestone_code": c, "milestone_name": n, "sequence_no": s}
               for c, n, s, _ in MILESTONES],
              ["milestone_key","milestone_code","milestone_name","sequence_no"])
    write_csv("fact_schedule_revision.csv", revisions,
              ["project_key","revision_id","revision_timestamp","revision_reason",
               "planned_start","planned_finish","forecast_finish","is_baseline"])
    write_csv("fact_project_snapshot.csv", snapshots,
              ["project_key","snapshot_date","status","forecast_finish",
               "current_stage","risk_status","progress_pct"])
    write_csv("fact_milestone_event.csv", events,
              ["project_key","milestone_key","planned_date","actual_date","event_status"])
    write_csv("dim_fiscal_date.csv", fiscal,
              ["calendar_date","fiscal_week","fiscal_month","fiscal_quarter","fiscal_year"])

    # Readiness draws from its own stream, after every table above is settled, so
    # adding it cannot move a single existing number. It is dated from the newest
    # snapshot -- the warehouse's own `data_as_of` -- not from the wall clock.
    vintage = max(s["snapshot_date"] for s in snapshots)
    readiness, golden_readiness_key = build_readiness(
        projects, random.Random(SEED), vintage)
    write_csv("dim_readiness_dimension.csv",
              [{"dimension_code": c, "dimension_name": n, "weight_pct": w, "sequence_no": s}
               for c, n, w, s in READINESS_DIMENSIONS],
              ["dimension_code","dimension_name","weight_pct","sequence_no"])
    write_csv("fact_readiness_assessment.csv", readiness,
              ["project_key","dimension_code","assessed_on","score_pct"])

    print(f"Generated {len(projects)} projects, {len(revisions)} schedule revisions, "
          f"{len(snapshots)} snapshots, {len(events)} milestone events, {len(fiscal)} fiscal dates.")
    print(f"Readiness: {len(readiness)} assessments across "
          f"{len(READINESS_DIMENSIONS)} dimensions "
          f"(weights sum to {sum(w for _c, _n, w, _s in READINESS_DIMENSIONS)}).")
    if golden:
        print(f"Golden project injected: {golden['project_id']} "
              f"(start {golden['actual_start']}, baseline {golden['_baseline_finish']}, "
              f"latest {golden['_force_latest_finish']}, actual {golden['actual_finish']}).")
    if golden_readiness_key:
        gid = next(p["project_id"] for p in projects
                   if p["project_key"] == golden_readiness_key)
        weighted = sum(GOLDEN_READINESS[c] * w for c, _n, w, _s in READINESS_DIMENSIONS) / 100.0
        print(f"Golden readiness injected: {gid} "
              f"(master plan §13 example -> {weighted:.2f}% overall).")


if __name__ == "__main__":
    main()
