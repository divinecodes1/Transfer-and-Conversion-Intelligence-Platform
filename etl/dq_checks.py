"""
Transfer & Conversion Intelligence Platform :: the three-tier data-quality framework.

Quality checks are useless in one big pile, because the tier a check belongs to
determines who fixes it and how urgently:

  INGESTION  the source sent something malformed. Not our bug. Quarantine the
             row, keep loading, and give the source owner a precise complaint.
  CORE       the canonical model is internally inconsistent -- a finish before a
             start, a baseline that moved after being frozen. Our bug, and it
             blocks: metrics computed over an incoherent core are worse than no
             metrics, because they look plausible.
  METRIC     the calculation layer disagrees with the data beneath it. Almost
             always a definition or population error, which is exactly the class
             of defect that shipped in this repo before the governance gate.

Each check returns rows that VIOLATE it. An empty result is a pass, so a check
that finds nothing costs nothing to report and a check that finds something hands
back the offending records rather than just a count.
"""

# Severity decides what happens to the row, and the distinction is the whole
# reason a quarantine is useful rather than annoying:
#
#   REJECT  the row cannot be trusted and must not reach CORE. A status outside
#           the domain or an unparseable date has no safe interpretation.
#   WARN    something is wrong with the *delivery*, but the pipeline already
#           resolves it deterministically -- a redelivered duplicate collapses in
#           staging. Worth telling the source owner about; not worth dropping
#           data for.
#
# Treating every finding as fatal is how teams end up disabling their own quality
# gates, because one duplicated row from an upstream system stops a portfolio.
REJECT, WARN = "REJECT", "WARN"

# --------------------------------------------------------------------------
# Tier 1 -- INGESTION. Run against tr_raw, before anything is typed or trusted.
# --------------------------------------------------------------------------
INGESTION = [
    ("project_key is unique in the batch", WARN,
     """SELECT project_key AS source_record_id,
               'appears ' || CAST(COUNT(*) AS VARCHAR) || ' times' AS detail
        FROM tr_raw.raw_project GROUP BY project_key HAVING COUNT(*) > 1"""),

    ("mandatory project fields are populated", REJECT,
     """SELECT project_key AS source_record_id, 'missing id/status/portfolio' AS detail
        FROM tr_raw.raw_project
        WHERE NULLIF(TRIM(COALESCE(project_id, '')), '') IS NULL
           OR NULLIF(TRIM(COALESCE(status, '')), '')     IS NULL
           OR NULLIF(TRIM(COALESCE(portfolio, '')), '')  IS NULL"""),

    ("dates parse", REJECT,
     """SELECT project_key AS source_record_id,
               'unparseable date: ' || COALESCE(actual_start, '') || ' / '
                                    || COALESCE(actual_finish, '') AS detail
        FROM tr_raw.raw_project
        WHERE (NULLIF(TRIM(actual_start), '')  IS NOT NULL
               AND tr_stg.to_date_safe(actual_start) IS NULL)
           OR (NULLIF(TRIM(actual_finish), '') IS NOT NULL
               AND tr_stg.to_date_safe(actual_finish) IS NULL)"""),

    ("status is in the approved domain", REJECT,
     """SELECT project_key AS source_record_id,
               'unknown status: ' || COALESCE(status, '(null)') AS detail
        FROM tr_raw.raw_project
        WHERE UPPER(TRIM(COALESCE(status, ''))) NOT IN
              ('COMPLETED', 'ACTIVE', 'PLANNED', 'CANCELLED')"""),

    ("schedule revisions reference a known project", WARN,
     """SELECT s.project_key AS source_record_id, 'orphan revision' AS detail
        FROM tr_raw.raw_schedule s
        LEFT JOIN tr_raw.raw_project p ON TRIM(p.project_key) = TRIM(s.project_key)
        WHERE p.project_key IS NULL"""),

    ("no exact duplicate deliveries", WARN,
     """SELECT record_hash AS source_record_id,
               'identical payload delivered ' || CAST(COUNT(*) AS VARCHAR)
               || ' times' AS detail
        FROM tr_raw.raw_project GROUP BY record_hash HAVING COUNT(*) > 1"""),
]

# --------------------------------------------------------------------------
# Tier 2 -- CORE. The canonical model must be internally coherent.
# --------------------------------------------------------------------------
CORE = [
    ("actual_finish >= actual_start",
     """SELECT CAST(project_key AS VARCHAR) AS source_record_id,
               'finish before start' AS detail
        FROM tr_core.dim_project
        WHERE actual_start IS NOT NULL AND actual_finish IS NOT NULL
          AND actual_finish < actual_start"""),

    ("every project has an immutable baseline",
     """SELECT CAST(p.project_key AS VARCHAR) AS source_record_id,
               'no baseline revision' AS detail
        FROM tr_core.dim_project p
        LEFT JOIN tr_core.fact_schedule_revision r
               ON r.project_key = p.project_key AND r.is_baseline
        WHERE r.project_key IS NULL"""),

    ("exactly one baseline per project",
     """SELECT CAST(project_key AS VARCHAR) AS source_record_id,
               CAST(COUNT(*) AS VARCHAR) || ' baselines' AS detail
        FROM tr_core.fact_schedule_revision WHERE is_baseline
        GROUP BY project_key HAVING COUNT(*) <> 1"""),

    ("revision timestamps are monotonic with revision_id",
     """SELECT CAST(a.project_key AS VARCHAR) AS source_record_id,
               'revision ' || CAST(a.revision_id AS VARCHAR)
               || ' is older than an earlier revision' AS detail
        FROM tr_core.fact_schedule_revision a
        JOIN tr_core.fact_schedule_revision b
          ON b.project_key = a.project_key AND b.revision_id < a.revision_id
        WHERE a.revision_timestamp < b.revision_timestamp"""),

    ("milestone sequence is valid",
     """SELECT CAST(e.project_key AS VARCHAR) AS source_record_id,
               'milestone out of sequence' AS detail
        FROM tr_core.fact_milestone_event e
        JOIN tr_core.dim_milestone m ON m.milestone_key = e.milestone_key
        JOIN tr_core.fact_milestone_event e2 ON e2.project_key = e.project_key
        JOIN tr_core.dim_milestone m2 ON m2.milestone_key = e2.milestone_key
        WHERE m2.sequence_no > m.sequence_no
          AND e.actual_date IS NOT NULL AND e2.actual_date IS NOT NULL
          AND e2.actual_date < e.actual_date"""),

    ("one snapshot per project per day",
     """SELECT CAST(project_key AS VARCHAR) AS source_record_id,
               'duplicate snapshot on ' || CAST(snapshot_date AS VARCHAR) AS detail
        FROM tr_core.fact_project_snapshot
        GROUP BY project_key, snapshot_date HAVING COUNT(*) > 1"""),

    ("schedule revisions resolve to a project",
     """SELECT CAST(r.project_key AS VARCHAR) AS source_record_id,
               'orphan revision' AS detail
        FROM tr_core.fact_schedule_revision r
        LEFT JOIN tr_core.dim_project p ON p.project_key = r.project_key
        WHERE p.project_key IS NULL"""),
]

# --------------------------------------------------------------------------
# Tier 3 -- METRIC. The calculation layer must agree with the data beneath it.
# --------------------------------------------------------------------------
METRIC = [
    ("cycle time is non-negative",
     """SELECT CAST(project_key AS VARCHAR) AS source_record_id,
               CAST(actual_cycle_time_days AS VARCHAR) || ' days' AS detail
        FROM tr_metric.v_project_cycle_time WHERE actual_cycle_time_days < 0"""),

    ("completion variance only exists for completed projects",
     """SELECT CAST(cv.project_key AS VARCHAR) AS source_record_id,
               'status is ' || p.status AS detail
        FROM tr_metric.v_completion_variance cv
        JOIN tr_core.dim_project p USING (project_key)
        WHERE p.status <> 'COMPLETED'"""),

    ("forecast error requires an actual outcome",
     """SELECT CAST(f.project_key AS VARCHAR) AS source_record_id,
               'no actual_finish' AS detail
        FROM tr_metric.v_forecast_error f
        JOIN tr_core.dim_project p USING (project_key)
        WHERE p.actual_finish IS NULL"""),

    ("cancelled projects are excluded from every metric",
     """SELECT CAST(p.project_key AS VARCHAR) AS source_record_id,
               'cancelled project present in a metric view' AS detail
        FROM tr_core.dim_project p
        WHERE p.status = 'CANCELLED'
          AND (p.project_key IN (SELECT project_key FROM tr_metric.v_schedule_deviation)
            OR p.project_key IN (SELECT project_key FROM tr_metric.v_stage_cycle_time)
            OR p.project_key IN (SELECT project_key FROM tr_metric.v_project_cycle_time))"""),

    ("throughput reconciles to the detail rows",
     """SELECT 'throughput' AS source_record_id,
               'mart says ' || CAST(m.total AS VARCHAR)
               || ', detail says ' || CAST(d.total AS VARCHAR) AS detail
        FROM (SELECT SUM(throughput) AS total FROM tr_mart.mart_portfolio_period) m
        CROSS JOIN (SELECT COUNT(*) AS total FROM tr_metric.v_project_kpi
                    WHERE status = 'COMPLETED'
                      AND completion_fiscal_year IS NOT NULL) d
        WHERE m.total <> d.total"""),

    ("distribution population reconciles to the detail rows",
     """SELECT 'distribution' AS source_record_id,
               'mart says ' || CAST(m.total AS VARCHAR)
               || ', detail says ' || CAST(d.total AS VARCHAR) AS detail
        FROM (SELECT SUM(n_projects) AS total
              FROM tr_mart.mart_cycle_time_distribution) m
        CROSS JOIN (SELECT COUNT(*) AS total FROM tr_metric.v_project_kpi
                    WHERE actual_cycle_time_days IS NOT NULL
                      AND completion_fiscal_year IS NOT NULL) d
        WHERE m.total <> d.total"""),
]

TIERS = [("INGESTION", INGESTION), ("CORE", CORE), ("METRIC", METRIC)]


def run_tier(con, tier_name, checks, batch_id=None, quarantine=True):
    """
    Run one tier. Returns [(check_name, severity, [violating rows])] for failures.

    CORE and METRIC checks carry no severity of their own: a violation there means
    the canonical model is incoherent, which blocks regardless of who caused it.
    """
    failures = []
    for check in checks:
        name, severity, sql = check if len(check) == 3 else (check[0], "BLOCK", check[1])
        rows = con.execute(sql).fetchall()
        if not rows:
            continue
        failures.append((name, severity, rows))
        if quarantine and batch_id is not None:
            for rec_id, detail in rows[:200]:
                con.execute(
                    "INSERT INTO tr_raw.quarantine (batch_id, quarantined_at, "
                    "source_table, tier, severity, check_name, source_record_id, "
                    "detail) VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)",
                    [batch_id, "raw_project" if tier_name == "INGESTION" else "core",
                     tier_name, severity, name, str(rec_id), str(detail)])
    return failures


def rejected_keys(con, batch_id):
    """Business keys held back from CORE because a REJECT-level check failed."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT source_record_id FROM tr_raw.quarantine "
        "WHERE batch_id = ? AND severity = 'REJECT'", [batch_id]).fetchall()]


def report(failures, tier_name, indent="  "):
    if not failures:
        print(f"{indent}[PASS] {tier_name}: all checks clean")
        return 0
    total = 0
    for name, severity, rows in failures:
        total += len(rows)
        print(f"{indent}[{severity:6}] {tier_name}: {name} - {len(rows)} row(s)")
        for rec_id, detail in rows[:3]:
            print(f"{indent}           {rec_id}: {detail}")
        if len(rows) > 3:
            print(f"{indent}           ... {len(rows) - 3} more")
    return total
