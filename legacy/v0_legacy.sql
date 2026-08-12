-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: legacy/v0_legacy.sql   -- THE "BEFORE" PICTURE
--
-- This file is deliberately bad. It is a faithful reconstruction of the pattern
-- described in interview: a reporting layer grown "on top, on top, on top" over several
-- years by successive contributors, each solving their own request correctly and
-- none of them owning the whole.
--
-- It is NOT a strawman. Read it closely and you will find that the headline
-- numbers are *right* -- cycle time, schedule deviation, completion variance and
-- on-time all reconcile exactly against the golden portfolio. That is precisely
-- what makes this pattern survive for years: it works. Nobody rewrites a
-- reporting stack that produces correct numbers.
--
-- What it costs shows up elsewhere:
--
--   * KPI formulas are inline, so every dashboard that needs "cycle time" writes
--     it again, and the definitions drift the moment one of them is edited.
--   * The baseline/latest resolution is duplicated in two subqueries. Changing
--     the rule means finding every copy.
--   * Magic filters and magic dates sit in the WHERE clause with no explanation
--     and no owner. Nobody remembers whether '2022-10-01' is a business rule or
--     a workaround for a data-migration artefact.
--   * There is no population definition anywhere, so whether cancelled projects
--     are in or out depends on which view you happened to open.
--   * Nothing is testable in isolation, so nothing gets tested.
--
-- And then there is VIEW_DASHBOARD_HEALTH_FIX at the bottom: a later addition,
-- bolted on for a specific request, which answers the same business question as
-- the main report using different thresholds and a different on-time rule -- it
-- scores completion against the LATEST replan instead of the frozen baseline.
-- Both views are "the dashboard". They disagree, and the second one flatters the
-- portfolio, because every replan moves the goalposts it is measured against.
-- Neither is wrong on its own terms, because no term was ever written down.
--
-- That is the actual failure mode -- not incorrect SQL, but two correct answers
-- to one question, with no way to say which the business meant.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS legacy;

DROP VIEW IF EXISTS legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2;
DROP VIEW IF EXISTS legacy.VIEW_DASHBOARD_HEALTH_FIX;

-- The main report. Note the inline formulas and the duplicated schedule
-- resolution -- the baseline subquery and the latest subquery are near-identical
-- and have to be maintained together, which of course they never are.
CREATE VIEW legacy.VIEW_PROJECT_REPORT_FINAL_NEW_V2 AS
SELECT
    p.project_id,
    p.transfer_type,
    p.portfolio,
    p.status,
    p.actual_start,
    p.actual_finish,

    -- cycle time (inline -- also copied into the cycle-time workbook and the
    -- monthly export script, which is where the three versions came from)
    CASE WHEN p.status = 'COMPLETED'
          AND p.actual_finish IS NOT NULL
          AND p.actual_start IS NOT NULL
         THEN p.actual_finish - p.actual_start
    END AS actual_cycle_time_days,

    -- schedule deviation (inline again, against the duplicated subqueries below)
    CASE WHEN p.status <> 'CANCELLED'
         THEN lat.planned_finish - bas.planned_finish
    END AS schedule_deviation_days,

    -- completion variance (inline, third repetition of the same date maths)
    CASE WHEN p.status = 'COMPLETED' AND p.actual_finish IS NOT NULL
         THEN p.actual_finish - bas.planned_finish
    END AS completion_variance_days,

    -- on-time (inline; measured against the FROZEN BASELINE here, and against the
    -- latest replan in the other view. Nobody noticed, and the two disagree badly.)
    CASE WHEN p.status = 'COMPLETED' AND p.actual_finish IS NOT NULL
         THEN CASE WHEN p.actual_finish <= bas.planned_finish THEN TRUE ELSE FALSE END
    END AS on_time

FROM tr_core.dim_project p

-- duplicated block 1 of 2: the baseline
LEFT JOIN (
    SELECT project_key, planned_finish
    FROM   tr_core.fact_schedule_revision
    WHERE  is_baseline = TRUE
) bas ON bas.project_key = p.project_key

-- duplicated block 2 of 2: the latest replan
LEFT JOIN (
    SELECT project_key, planned_finish
    FROM (
        SELECT project_key, planned_finish,
               ROW_NUMBER() OVER (PARTITION BY project_key
                                  ORDER BY revision_timestamp DESC, revision_id DESC) rn
        FROM tr_core.fact_schedule_revision
    ) z
    WHERE rn = 1
) lat ON lat.project_key = p.project_key

-- magic filters. Origin unknown, owner unknown, never documented.
WHERE p.project_id NOT LIKE 'X-%'
  AND COALESCE(p.actual_start, DATE '2022-10-01') >= DATE '2022-10-01';


-- Bolted on later for a specific management request. Same business question,
-- different thresholds, different on-time rule. This is the drift.
CREATE VIEW legacy.VIEW_DASHBOARD_HEALTH_FIX AS
SELECT
    p.project_id,
    p.portfolio,
    p.status,

    -- on-time, take two: measured against the LATEST replan rather than the frozen
    -- baseline. Entirely defensible if you were the person who wrote it ("did we
    -- hit the plan we were working to?"), and it flatters the portfolio enormously,
    -- because every replan moves the goalposts it is scored against. A project can
    -- slip a year and still be "on time" here as long as the plan slipped with it.
    -- This is metric gaming without anyone intending to game anything.
    CASE WHEN p.status = 'COMPLETED' AND p.actual_finish IS NOT NULL
         THEN CASE WHEN p.actual_finish <= lat.planned_finish THEN TRUE ELSE FALSE END
    END AS on_time,

    -- health bands, take two: 7/21 days here, 0/30 in the other dashboard.
    CASE
        WHEN lat.planned_finish - bas.planned_finish IS NULL THEN 'UNKNOWN'
        WHEN lat.planned_finish - bas.planned_finish <= 7  THEN 'ON_TRACK'
        WHEN lat.planned_finish - bas.planned_finish <= 21 THEN 'AT_RISK'
        ELSE 'DELAYED'
    END AS health

FROM tr_core.dim_project p
LEFT JOIN (
    SELECT project_key, planned_finish
    FROM   tr_core.fact_schedule_revision
    WHERE  is_baseline = TRUE
) bas ON bas.project_key = p.project_key
LEFT JOIN (
    SELECT project_key, planned_finish
    FROM (
        SELECT project_key, planned_finish,
               ROW_NUMBER() OVER (PARTITION BY project_key
                                  ORDER BY revision_timestamp DESC, revision_id DESC) rn
        FROM tr_core.fact_schedule_revision
    ) z
    WHERE rn = 1
) lat ON lat.project_key = p.project_key
WHERE p.status IN ('ACTIVE', 'PLANNED', 'COMPLETED');
