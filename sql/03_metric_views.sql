-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 03_metric_views.sql
-- The CALCULATION LAYER. Each KPI is defined exactly once here and reused
-- everywhere (marts, Tableau, AI agent). No dashboard recomputes a metric.
-- Date arithmetic uses (date2 - date1), which returns integer days in BOTH
-- PostgreSQL and DuckDB, so this file is portable and directly testable.
-- ============================================================================

-- ---- Schedule history resolution -----------------------------------------

-- The frozen original commitment.
CREATE OR REPLACE VIEW tr_metric.v_baseline_schedule AS
SELECT project_key,
       planned_start  AS baseline_start,
       planned_finish AS baseline_finish
FROM   tr_core.fact_schedule_revision
WHERE  is_baseline = TRUE;

-- The most recent replan.
CREATE OR REPLACE VIEW tr_metric.v_latest_schedule AS
SELECT project_key, planned_start AS latest_start, planned_finish AS latest_finish,
       forecast_finish AS latest_forecast_finish
FROM (
    SELECT r.*,
           ROW_NUMBER() OVER (PARTITION BY project_key
                              ORDER BY revision_timestamp DESC, revision_id DESC) AS rn
    FROM tr_core.fact_schedule_revision r
) s
WHERE rn = 1;

-- ---- Core project metrics -------------------------------------------------

-- ACTUAL_TRANSFER_CYCLE_TIME
CREATE OR REPLACE VIEW tr_metric.v_project_cycle_time AS
SELECT p.project_key, p.project_id, p.transfer_type, p.portfolio,
       p.actual_start, p.actual_finish,
       (p.actual_finish - p.actual_start) AS actual_cycle_time_days
FROM   tr_core.dim_project p
WHERE  p.status = 'COMPLETED'
  AND  p.actual_start  IS NOT NULL
  AND  p.actual_finish IS NOT NULL;

-- FORECAST_CYCLE_TIME (expected speed, as believed at each snapshot date).
-- The retrospective twin of v_project_cycle_time: same grain of question, but
-- forward-looking, which is the "forecast vs history" comparison from the interview.
CREATE OR REPLACE VIEW tr_metric.v_forecast_cycle_time AS
SELECT s.project_key, p.project_id, p.transfer_type, p.portfolio,
       s.snapshot_date, p.actual_start, s.forecast_finish,
       (s.forecast_finish - p.actual_start) AS forecast_cycle_time_days
FROM   tr_core.fact_project_snapshot s
JOIN   tr_core.dim_project p USING (project_key)
WHERE  p.status <> 'CANCELLED'
  AND  p.actual_start    IS NOT NULL
  AND  s.forecast_finish IS NOT NULL;

-- BASELINE_FINISH_DEVIATION_DAYS (original vs latest; auditable because the two
-- values come from separate schedule rows, not a workbook calc).
-- Cancelled projects are excluded per the registered definition: they keep a
-- baseline, so without this filter their abandoned replans would silently score
-- as portfolio slippage.
CREATE OR REPLACE VIEW tr_metric.v_schedule_deviation AS
SELECT b.project_key, b.baseline_finish, l.latest_finish,
       (l.latest_finish - b.baseline_finish) AS schedule_deviation_days
FROM   tr_metric.v_baseline_schedule b
JOIN   tr_metric.v_latest_schedule  l USING (project_key)
JOIN   tr_core.dim_project          p USING (project_key)
WHERE  p.status <> 'CANCELLED';

-- COMPLETION_VARIANCE_DAYS + on-time flag
CREATE OR REPLACE VIEW tr_metric.v_completion_variance AS
SELECT p.project_key, p.project_id,
       b.baseline_finish, p.actual_finish,
       (p.actual_finish - b.baseline_finish) AS completion_variance_days,
       CASE WHEN p.actual_finish <= b.baseline_finish THEN TRUE ELSE FALSE END AS on_time
FROM   tr_core.dim_project p
JOIN   tr_metric.v_baseline_schedule b USING (project_key)
WHERE  p.status = 'COMPLETED' AND p.actual_finish IS NOT NULL;

-- FORECAST_ERROR_DAYS at controlled horizons (snapshot forecast vs eventual actual).
-- horizon_days = how far before completion the forecast was made.
CREATE OR REPLACE VIEW tr_metric.v_forecast_error AS
SELECT s.project_key, s.snapshot_date, s.forecast_finish, p.actual_finish,
       (p.actual_finish - s.snapshot_date)     AS horizon_days,
       (p.actual_finish - s.forecast_finish)   AS forecast_error_days,
       ABS(p.actual_finish - s.forecast_finish) AS abs_forecast_error_days
FROM   tr_core.fact_project_snapshot s
JOIN   tr_core.dim_project p USING (project_key)
WHERE  p.status = 'COMPLETED' AND p.actual_finish IS NOT NULL
  AND  s.forecast_finish IS NOT NULL;

-- The horizon buckets forecast error is read at. Defined here rather than in the
-- API because two consumers now read them -- the PMO horizon curve and the
-- forecast-accuracy screen -- and a bucket boundary written twice is a bucket
-- boundary that will eventually be written differently.
CREATE OR REPLACE VIEW tr_metric.v_forecast_error_horizon AS
SELECT e.*,
       CASE WHEN e.horizon_days >= 90 THEN '90+'
            WHEN e.horizon_days >= 60 THEN '60-89'
            WHEN e.horizon_days >= 30 THEN '30-59'
            ELSE '0-29' END                                  AS horizon_bucket,
       CASE WHEN e.horizon_days >= 90 THEN 90
            WHEN e.horizon_days >= 60 THEN 60
            WHEN e.horizon_days >= 30 THEN 30
            ELSE 0 END                                       AS horizon_floor,
       -- "Close enough to plan a handover around" -- the hit-rate threshold, named
       -- once so a screen cannot quietly move it to make a chart look better.
       CASE WHEN e.abs_forecast_error_days <= 14 THEN TRUE
            ELSE FALSE END                                   AS within_14_days
FROM   tr_metric.v_forecast_error e
WHERE  e.horizon_days >= 0;

-- STAGE_CYCLE_TIME (milestone-to-milestone; bottleneck detection)
CREATE OR REPLACE VIEW tr_metric.v_stage_cycle_time AS
SELECT e1.project_key,
       m1.milestone_code AS from_stage,
       m2.milestone_code AS to_stage,
       m1.sequence_no    AS from_seq,
       (e2.actual_date - e1.actual_date) AS stage_cycle_time_days
FROM   tr_core.fact_milestone_event e1
JOIN   tr_core.dim_milestone m1 ON m1.milestone_key = e1.milestone_key
JOIN   tr_core.dim_milestone m2 ON m2.sequence_no  = m1.sequence_no + 1
JOIN   tr_core.fact_milestone_event e2
       ON e2.project_key = e1.project_key AND e2.milestone_key = m2.milestone_key
JOIN   tr_core.dim_project p ON p.project_key = e1.project_key
WHERE  e1.actual_date IS NOT NULL AND e2.actual_date IS NOT NULL
  AND  p.status <> 'CANCELLED';   -- stages a cancelled project happened to clear
                                  -- are not evidence about how long a stage takes

-- ---- Data vintage ---------------------------------------------------------
-- How current the warehouse is, expressed in the data's own terms: the newest
-- project snapshot we hold. Anything time-relative below is measured against
-- THIS rather than against CURRENT_DATE, so "WIP age" is reproducible -- a number
-- printed in a report last Tuesday still recomputes to the same value today, and
-- the golden gate does not start failing overnight because the clock moved.
CREATE OR REPLACE VIEW tr_metric.v_data_vintage AS
SELECT MAX(snapshot_date) AS data_as_of
FROM   tr_core.fact_project_snapshot;

-- REPLAN_RATE's project-grain input. The baseline row is a revision too, so a
-- project that was never replanned still has revision_count = 1 -- which is why
-- the flag is "> 1" and not "> 0".
CREATE OR REPLACE VIEW tr_metric.v_project_replan AS
SELECT r.project_key,
       COUNT(*)                                            AS revision_count,
       COUNT(*) - 1                                        AS replan_count,
       CASE WHEN COUNT(*) > 1 THEN TRUE ELSE FALSE END     AS was_replanned,
       MAX(r.revision_timestamp)                           AS last_revised_at
FROM   tr_core.fact_schedule_revision r
JOIN   tr_core.dim_project p USING (project_key)
WHERE  p.status <> 'CANCELLED'
GROUP  BY r.project_key;

-- WIP_AGE_DAYS: how long an in-flight project has already been running. The
-- population is the point -- a completed project has a cycle time, not a WIP age,
-- and mixing the two is how "average duration" quietly starts excluding every
-- project that is currently hurting.
CREATE OR REPLACE VIEW tr_metric.v_project_wip AS
SELECT p.project_key, p.project_id, p.transfer_type, p.portfolio,
       p.actual_start,
       ((SELECT data_as_of FROM tr_metric.v_data_vintage) - p.actual_start)
                                                           AS wip_age_days
FROM   tr_core.dim_project p
WHERE  p.status <> 'CANCELLED'
  AND  p.actual_start  IS NOT NULL
  AND  p.actual_finish IS NULL;

-- ---- One governed row per project (the materialisable KPI table) ----------
CREATE OR REPLACE VIEW tr_metric.v_project_kpi AS
SELECT
    p.project_key, p.project_id, p.project_name,
    p.transfer_type, p.complexity_class,
    p.portfolio, p.source_site, p.target_site, p.status,
    p.actual_start, p.actual_finish,
    b.baseline_start, b.baseline_finish,
    l.latest_start, l.latest_finish, l.latest_forecast_finish,
    ct.actual_cycle_time_days,
    sd.schedule_deviation_days,
    cv.completion_variance_days,
    cv.on_time,
    rp.revision_count,
    rp.replan_count,
    rp.was_replanned,
    rp.last_revised_at,
    w.wip_age_days,
    fy.fiscal_year AS completion_fiscal_year,
    sfy.fiscal_year AS start_fiscal_year
FROM        tr_core.dim_project p
LEFT JOIN   tr_metric.v_baseline_schedule   b  USING (project_key)
LEFT JOIN   tr_metric.v_latest_schedule     l  USING (project_key)
LEFT JOIN   tr_metric.v_project_cycle_time  ct USING (project_key)
LEFT JOIN   tr_metric.v_schedule_deviation  sd USING (project_key)
LEFT JOIN   tr_metric.v_completion_variance cv USING (project_key)
LEFT JOIN   tr_metric.v_project_replan      rp USING (project_key)
LEFT JOIN   tr_metric.v_project_wip         w  USING (project_key)
LEFT JOIN   tr_core.dim_fiscal_date         fy  ON fy.calendar_date  = p.actual_finish
LEFT JOIN   tr_core.dim_fiscal_date         sfy ON sfy.calendar_date = p.actual_start;
