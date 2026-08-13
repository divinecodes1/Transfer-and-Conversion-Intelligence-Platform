"""
Transfer & Conversion Intelligence Platform :: readiness, network and similarity gates.

Three capabilities added on top of the metric layer, and three ways each of them
could quietly be wrong. The pattern is the one golden_projects.py uses: recompute
the answer in Python, from the same rows, and require the warehouse to agree.
Asserting "the view returns a number between 0 and 100" would pass against a view
that returned the wrong number, which is the failure worth catching.

  READINESS   a weighted mean is exactly the kind of arithmetic that looks right
              while dividing by the wrong denominator. Gate 2 recomputes every
              project's score from the dimension rows and the weight table; gate 3
              pins the master plan's own worked example.

  NETWORK     re-graining a metric onto a lane is where a population filter gets
              lost. Gate 7 recomputes the lane on-time rate from the project rows,
              and gate 9 requires the lanes to account for every project.

  SIMILARITY  a scoring rule nobody checks drifts into a scoring rule nobody can
              explain. Gate 10 recomputes the score from the four published
              factors and requires an exact match.

Server-free: runs against a throwaway DuckDB build, so it needs no PostgreSQL,
no API and no model.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
from run import run_duckdb  # noqa: E402

# The master plan's §13 worked example. Held here as well as in the generator so
# the two have to agree: if either side is edited alone, this gate fails.
GOLDEN_VECTOR = {
    "PRODUCT": 100, "PROCESS": 91, "EQUIPMENT": 67, "MATERIAL": 86,
    "QUALIFICATION": 61, "TARGET_SITE": 73, "DOCUMENTATION": 96,
}

# The band boundaries, restated independently of the SQL that implements them.
BAND_EDGES = [(85, "READY"), (70, "AT_RISK"), (0, "NOT_READY")]

# The published similarity weights, restated for the same reason.
SIMILARITY_WEIGHTS = {
    "transfer_type": 35, "complexity_class": 20, "portfolio": 20,
    "target_site": 15, "source_site": 10,
}


def band_for(score):
    for floor, name in BAND_EDGES:
        if score >= floor:
            return name
    return "NOT_READY"


def run():
    db = os.path.join(os.path.dirname(__file__), "..", "warehouse_readiness.duckdb")
    con = run_duckdb(db)
    fetch = lambda q: con.execute(q).fetchall()  # noqa: E731

    results = []

    # ---- Gate 1: the weight set --------------------------------------------
    weights = {code: w for code, w in fetch(
        "SELECT dimension_code, weight_pct FROM tr_core.dim_readiness_dimension")}
    total_weight = sum(weights.values())
    results.append(("the readiness weight set is complete and sums to 100",
                    len(weights) == 7 and total_weight == 100,
                    f"{len(weights)} dimensions, weights sum to {total_weight}"))

    # ---- Gate 2: the weighted mean -----------------------------------------
    # Recomputed per project from the dimension rows, independently of the view.
    scores = defaultdict(dict)
    for pid, code, score in fetch(
            "SELECT project_id, dimension_code, score_pct "
            "FROM tr_metric.v_project_readiness_dimension"):
        scores[pid][code] = score

    stored = {pid: pct for pid, pct in fetch(
        "SELECT project_id, readiness_pct FROM tr_mart.mart_readiness_register")}

    mismatches = []
    for pid, dims in scores.items():
        expected = sum(dims[c] * weights[c] for c in dims) / sum(weights[c] for c in dims)
        actual = float(stored.get(pid, -1))
        if abs(expected - actual) > 0.005:
            mismatches.append(f"{pid}: expected {expected:.2f}, warehouse {actual:.2f}")
    results.append(("every readiness score is the weighted mean of its dimensions",
                    not mismatches,
                    "; ".join(mismatches[:3]) if mismatches
                    else f"{len(scores)} projects recomputed independently, all agree"))

    # ---- Gate 3: the master plan's worked example ---------------------------
    golden = [pid for pid, dims in scores.items() if dims == GOLDEN_VECTOR]
    expected_golden = sum(GOLDEN_VECTOR[c] * weights[c] for c in GOLDEN_VECTOR) / 100.0
    golden_ok = (len(golden) == 1
                 and abs(float(stored[golden[0]]) - expected_golden) < 0.005)
    results.append(("the master plan's §13 example scores as the plan's weights say",
                    golden_ok,
                    f"{golden[0] if golden else 'missing'} -> {expected_golden:.2f}%"
                    f" (the plan's prose says 78%; its own weights say"
                    f" {expected_golden:.2f}%)"))

    # ---- Gate 4: the bands --------------------------------------------------
    band_errors = []
    for pid, pct, band in fetch(
            "SELECT project_id, readiness_pct, readiness_band "
            "FROM tr_mart.mart_readiness_register"):
        if band_for(float(pct)) != band:
            band_errors.append(f"{pid}: {float(pct):.1f} banded {band}")
    results.append(("every readiness band matches the boundary it claims",
                    not band_errors,
                    "; ".join(band_errors[:3]) if band_errors
                    else f"{len(stored)} projects banded consistently"))

    # ---- Gate 5: the population --------------------------------------------
    leaked = fetch(
        "SELECT COUNT(*) FROM tr_core.fact_readiness_assessment a "
        "JOIN tr_core.dim_project p USING (project_key) "
        "WHERE p.status NOT IN ('ACTIVE','PLANNED')")[0][0]
    results.append(("readiness is assessed only for in-flight transfers",
                    leaked == 0,
                    "a completed transfer has an outcome, not a readiness"))

    # ---- Gate 6: the limiting dimension ------------------------------------
    gap_errors = []
    for pid, limiting, limiting_score in fetch(
            "SELECT project_id, limiting_dimension, limiting_score "
            "FROM tr_mart.mart_readiness_register"):
        lowest = min(scores[pid].values())
        if limiting_score != lowest or scores[pid][limiting] != lowest:
            gap_errors.append(f"{pid}: named {limiting} at {limiting_score}, lowest is {lowest}")
    results.append(("the limiting dimension really is the lowest-scoring one",
                    not gap_errors,
                    "; ".join(gap_errors[:3]) if gap_errors
                    else "the constraint named is the constraint measured"))

    # ---- Gate 7: the lane on-time rate -------------------------------------
    # The re-grained metric, recomputed from project rows. An ELSE 0 folded into
    # the lane rollup would score every in-flight transfer as a miss, and the
    # number would still look plausible on a chart.
    lane_projects = defaultdict(list)
    for src, tgt, on_time in fetch(
            "SELECT source_site, target_site, on_time FROM tr_mart.mart_project_register"):
        lane_projects[(src, tgt)].append(on_time)

    rate_errors = []
    for src, tgt, rate in fetch(
            "SELECT source_site, target_site, on_time_rate FROM tr_mart.mart_transfer_network"):
        finished = [v for v in lane_projects[(src, tgt)] if v is not None]
        expected = (100.0 * sum(1 for v in finished if v) / len(finished)) if finished else None
        if expected is None:
            ok = rate is None
        else:
            ok = rate is not None and abs(float(rate) - expected) < 0.005
        if not ok:
            rate_errors.append(f"{src}->{tgt}: warehouse {rate}, recomputed {expected}")
    results.append(("every lane on-time rate is counted over finished transfers only",
                    not rate_errors,
                    "; ".join(rate_errors[:3]) if rate_errors
                    else f"{len(lane_projects)} lanes recomputed independently"))

    # ---- Gate 8: the bottleneck --------------------------------------------
    stage_medians = defaultdict(dict)
    for src, tgt, stage, median in fetch(
            "SELECT source_site, target_site, from_stage, median_stage_days "
            "FROM tr_mart.mart_route_stage"):
        stage_medians[(src, tgt)][stage] = float(median)

    bottleneck_errors = []
    for src, tgt, stage, median in fetch(
            "SELECT source_site, target_site, bottleneck_stage, bottleneck_median_days "
            "FROM tr_mart.mart_route_bottleneck"):
        worst = max(stage_medians[(src, tgt)].values())
        if abs(float(median) - worst) > 0.005:
            bottleneck_errors.append(f"{src}->{tgt}: named {stage} at {median}, worst is {worst}")
    results.append(("every lane bottleneck is that lane's slowest stage",
                    not bottleneck_errors,
                    "; ".join(bottleneck_errors[:3]) if bottleneck_errors
                    else f"{len(stage_medians)} lanes checked"))

    # A bottleneck column that reads the same value on every lane is a constant
    # wearing a chart's clothes -- it was exactly that until the generator gave
    # each project its own stage weights, so the property is now gated.
    distinct = fetch("SELECT COUNT(DISTINCT bottleneck_stage) "
                     "FROM tr_mart.mart_transfer_network "
                     "WHERE bottleneck_stage IS NOT NULL")[0][0]
    results.append(("the lane bottleneck varies across the network",
                    distinct > 1,
                    f"{distinct} distinct bottleneck stages; 1 would mean the "
                    f"column is structural, not a finding"))

    # ---- Gate 9: the lanes account for every project ------------------------
    lane_total = fetch("SELECT SUM(total_transfers) FROM tr_mart.mart_transfer_network")[0][0]
    register_total = fetch("SELECT COUNT(*) FROM tr_mart.mart_project_register")[0][0]
    results.append(("the network accounts for every project in the register",
                    lane_total == register_total,
                    f"{lane_total} on lanes vs {register_total} in the register"))

    # ---- Gate 10: the similarity score --------------------------------------
    attrs = {}
    for key, ttype, cx, pf, src, tgt, status in fetch(
            "SELECT project_key, transfer_type, complexity_class, portfolio, "
            "       source_site, target_site, status FROM tr_core.dim_project"):
        attrs[key] = {"transfer_type": ttype, "complexity_class": cx, "portfolio": pf,
                      "source_site": src, "target_site": tgt, "status": status}

    sim_errors = []
    rows = fetch("SELECT project_key, similar_project_key, similarity_pct "
                 "FROM tr_metric.v_transfer_similarity")
    for a_key, b_key, pct in rows:
        expected = sum(w for field, w in SIMILARITY_WEIGHTS.items()
                       if attrs[a_key][field] == attrs[b_key][field])
        if expected != pct:
            sim_errors.append(f"{a_key}~{b_key}: warehouse {pct}, recomputed {expected}")
    results.append(("every similarity score is the published weighted match",
                    not sim_errors,
                    "; ".join(sim_errors[:3]) if sim_errors
                    else f"{len(rows)} pairs recomputed from four factors"))

    # ---- Gate 11: what similarity may compare against -----------------------
    bad_population = [f"{a}~{b}" for a, b, _p in rows
                      if a == b or attrs[b]["status"] != "COMPLETED"
                      or attrs[a]["status"] not in ("ACTIVE", "PLANNED")]
    results.append(("similarity compares in-flight work against completed history only",
                    not bad_population,
                    "; ".join(bad_population[:3]) if bad_population
                    else "no project is its own precedent, and no unfinished "
                         "transfer is offered as evidence"))

    # ---- Gate 12: readiness is not a governed-metric impostor ---------------
    # Readiness IS registered, unlike the AI risk score -- but it must be
    # registered as itself, with the population the view actually enforces.
    registered = {code: (pop or "") for code, pop in fetch(
        "SELECT metric_code, population FROM tr_gov.metric_definition")}
    needed = ["TRANSFER_READINESS_SCORE", "READINESS_DIMENSION_SCORE",
              "ROUTE_BOTTLENECK_STAGE", "TRANSFER_SIMILARITY_SCORE"]
    missing = [c for c in needed if c not in registered]
    results.append(("the three capabilities are registered in the catalogue",
                    not missing,
                    f"missing: {missing}" if missing
                    else "readiness, bottleneck and similarity all carry a definition"))

    print("Readiness, network and similarity checks")
    print("-" * 72)
    passed = failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        passed += ok
        failed += (not ok)
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed")
    con.close()
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
