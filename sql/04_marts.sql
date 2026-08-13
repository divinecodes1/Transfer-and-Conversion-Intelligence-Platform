-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 04_marts.sql
-- Curated reporting marts. Tableau/Superset consume THESE, not core tables,
-- and never re-implement metric logic. Two audiences:
--   * technical/PMO  -> distribution + drill-down marts
--   * management     -> portfolio period rollups
-- ============================================================================

-- Box-plot source: cycle-time distribution by fiscal year x transfer type.
-- (The existing reporting specifically showed box plots of cycle time spread
--  across fiscal years.)
CREATE OR REPLACE VIEW tr_mart.mart_cycle_time_distribution AS
SELECT
    completion_fiscal_year AS fiscal_year,
    transfer_type,
    COUNT(*)                                                           AS n_projects,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY actual_cycle_time_days) AS p25,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY actual_cycle_time_days) AS p50_median,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY actual_cycle_time_days) AS p75,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY actual_cycle_time_days) AS p90,
    MIN(actual_cycle_time_days)                                         AS min_days,
    MAX(actual_cycle_time_days)                                         AS max_days
FROM tr_metric.v_project_kpi
WHERE actual_cycle_time_days IS NOT NULL
GROUP BY completion_fiscal_year, transfer_type;

-- Management rollup: throughput, median cycle time, on-time rate, avg slip.
CREATE OR REPLACE VIEW tr_mart.mart_portfolio_period AS
SELECT
    completion_fiscal_year AS fiscal_year,
    portfolio,
    COUNT(*)                                                             AS throughput,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY actual_cycle_time_days)   AS median_cycle_time,
    AVG(CASE WHEN on_time THEN 1.0 ELSE 0.0 END)                          AS on_time_rate,
    AVG(completion_variance_days)                                         AS avg_completion_variance
FROM tr_metric.v_project_kpi
WHERE status = 'COMPLETED'
GROUP BY completion_fiscal_year, portfolio;

-- ---------------------------------------------------------------------------
-- The project register: one governed row per live project, at project grain.
--
-- This is the mart the register table, the KPI tiles, the risk scorer and the
-- assistant all read. It is deliberately NOT pre-aggregated: aggregation that has
-- already happened cannot be filtered afterwards, and every screen here filters.
-- So the grain stays at the project and the rollups are composed over this view
-- from whitelisted governed columns -- the numbers still come from one place, and
-- a filtered KPI tile does not need a second definition of anything.
--
-- The health band lives here and nowhere else. It used to be inline in
-- mart_project_status; the moment a second consumer wanted "how many are late?"
-- that inline CASE became a threshold about to be re-declared somewhere warmer.
CREATE OR REPLACE VIEW tr_mart.mart_project_register AS
SELECT
    k.project_key, k.project_id, k.project_name,
    k.transfer_type, k.complexity_class, k.portfolio,
    k.product_line, k.product_name,
    k.application_segment, k.application_name,
    k.source_site, k.target_site, k.status,
    k.actual_start, k.actual_finish,
    k.baseline_start, k.baseline_finish,
    k.latest_start, k.latest_finish, k.latest_forecast_finish,
    k.actual_cycle_time_days,
    k.schedule_deviation_days,
    k.completion_variance_days,
    k.on_time,
    k.revision_count, k.replan_count, k.was_replanned, k.last_revised_at,
    k.wip_age_days,
    k.completion_fiscal_year, k.start_fiscal_year,
    CASE
        WHEN k.schedule_deviation_days IS NULL   THEN 'UNKNOWN'
        WHEN k.schedule_deviation_days <= 0      THEN 'ON_TRACK'
        WHEN k.schedule_deviation_days <= 30     THEN 'AT_RISK'
        ELSE 'LATE'
    END AS health
FROM tr_metric.v_project_kpi k
WHERE k.status <> 'CANCELLED';

-- Current operational status: one row per active/planned project with live slip.
-- Now a population filter over the register rather than a second copy of the
-- banding rule -- the existing column contract is unchanged.
CREATE OR REPLACE VIEW tr_mart.mart_project_status AS
SELECT
    project_id, transfer_type, complexity_class, portfolio,
    source_site, target_site, status,
    baseline_finish, latest_finish,
    schedule_deviation_days,
    health
FROM tr_mart.mart_project_register
WHERE status IN ('ACTIVE','PLANNED');

-- The filter vocabulary, read from the data rather than hard-coded in a browser.
-- A dropdown listing a site nobody transfers to, or missing one that appeared last
-- quarter, is the same drift problem as a stale metric definition -- so the option
-- list is derived, and it is derived through the register, which means it is
-- entitlement-scoped like everything else: you cannot enumerate a portfolio you
-- are not allowed to see.
-- Each option carries the value a filter binds on AND the label a human reads.
--
-- They are the same string for most dimensions -- a site is called what it is
-- called. They diverge for the product and application taxonomy, where the
-- filter must bind on a stable code (`SECURITY_CARD`) while the dropdown has
-- to read "Security & Smart Card Solutions".
--
-- Both come from here rather than the browser deriving one from the other,
-- because a client-side prettifier is a second naming authority: the day the
-- catalogue renames a line, the filter list and the chart axis disagree and
-- only one of them is right.
CREATE OR REPLACE VIEW tr_mart.mart_filter_options AS
SELECT 'fiscal_year' AS dimension,
       CAST(completion_fiscal_year AS VARCHAR) AS value,
       CAST(completion_fiscal_year AS VARCHAR) AS label
FROM   tr_mart.mart_project_register WHERE completion_fiscal_year IS NOT NULL
UNION
SELECT 'transfer_type', transfer_type, transfer_type
FROM   tr_mart.mart_project_register WHERE transfer_type IS NOT NULL
UNION
SELECT 'portfolio', portfolio, portfolio
FROM   tr_mart.mart_project_register WHERE portfolio IS NOT NULL
UNION
SELECT 'complexity_class', complexity_class, complexity_class
FROM   tr_mart.mart_project_register WHERE complexity_class IS NOT NULL
UNION
SELECT 'source_site', source_site, source_site
FROM   tr_mart.mart_project_register WHERE source_site IS NOT NULL
UNION
SELECT 'target_site', target_site, target_site
FROM   tr_mart.mart_project_register WHERE target_site IS NOT NULL
UNION
SELECT 'product_line', product_line, product_name
FROM   tr_mart.mart_project_register WHERE product_line IS NOT NULL
UNION
SELECT 'application_segment', application_segment, application_name
FROM   tr_mart.mart_project_register WHERE application_segment IS NOT NULL
UNION
SELECT 'status', status, status
FROM   tr_mart.mart_project_register WHERE status IS NOT NULL
UNION
SELECT 'health', health, health
FROM   tr_mart.mart_project_register WHERE health IS NOT NULL;
