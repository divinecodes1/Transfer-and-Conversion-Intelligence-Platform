-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 13_readiness_network.sql
--
-- Three capabilities the master plan calls signature features, all of them
-- computed HERE rather than in a service, for the reason every other metric is:
-- a definition that lives in one place can be audited, and one that lives in a
-- component gets a second copy the first time another screen wants it.
--
--   1. READINESS   -- how prepared is an in-flight transfer, by weighted
--                     dimension, with the weights stored as data.
--   2. NETWORK     -- the same governed metrics re-grained onto the site-to-site
--                     lane, plus the stage that costs each lane the most time.
--   3. SIMILARITY  -- which completed transfers resemble an in-flight one, scored
--                     deterministically so the answer can be defended.
--
-- Runs after 03/04 (it reads the metric layer and the project register) and
-- before 10_rls.sql, which applies security_invoker to every view in tr_metric
-- and tr_mart -- so everything below is entitlement-scoped without naming a
-- policy, exactly like the views that came before it.
-- ============================================================================

-- ---- 1. Readiness ---------------------------------------------------------

-- One row per project per dimension, carrying the weight the dimension is worth.
--
-- The population is enforced here rather than in every consumer: readiness is a
-- question about work still ahead, so a completed project does not have one. If
-- this filter moved to the API, the first caller that forgot it would report a
-- portfolio average quietly diluted by finished work scoring full marks.
CREATE OR REPLACE VIEW tr_metric.v_project_readiness_dimension AS
SELECT a.project_key,
       p.project_id,
       d.dimension_code,
       d.dimension_name,
       d.weight_pct,
       d.sequence_no,
       a.score_pct,
       a.assessed_on
FROM   tr_core.fact_readiness_assessment a
JOIN   tr_core.dim_readiness_dimension   d USING (dimension_code)
JOIN   tr_core.dim_project               p USING (project_key)
WHERE  p.status IN ('ACTIVE', 'PLANNED');

-- The dimension holding a project back. Ties break on weight, then on sequence:
-- when two dimensions score the same, the one that moves the overall number most
-- is the one worth naming, and naming it consistently matters more than which
-- one wins -- an arg-min that reorders between runs makes "the limiting factor"
-- look like it changed when nothing did.
CREATE OR REPLACE VIEW tr_metric.v_project_readiness_gap AS
SELECT project_key,
       dimension_code AS limiting_dimension,
       dimension_name AS limiting_dimension_name,
       score_pct      AS limiting_score,
       weight_pct     AS limiting_weight
FROM (
    SELECT d.*,
           ROW_NUMBER() OVER (PARTITION BY d.project_key
                              ORDER BY d.score_pct ASC,
                                       d.weight_pct DESC,
                                       d.sequence_no ASC) AS rn
    FROM   tr_metric.v_project_readiness_dimension d
) ranked
WHERE rn = 1;

-- TRANSFER_READINESS_SCORE.
--
-- The weighted mean names no dimension: it multiplies by whatever weight the
-- dimension table carries and divides by whatever those weights sum to. Adding an
-- eighth dimension or re-weighting an existing one is an INSERT or an UPDATE, not
-- an edit to this file -- which is the difference between a business rule the
-- business can change and one only engineering can.
--
-- `* 1.0` is load-bearing: both operands are integers, and integer division in
-- PostgreSQL would silently floor every readiness score to a whole percent below
-- its true value. DuckDB would not, so the bug would only appear in production.
CREATE OR REPLACE VIEW tr_metric.v_project_readiness AS
SELECT s.project_key,
       s.readiness_pct,
       s.dimensions_assessed,
       s.oldest_assessment,
       s.newest_assessment,
       -- The readiness bands. Declared once, here, for the same reason the health
       -- band lives only in mart_project_register: tests/web_checks.py asserts the
       -- console never re-derives a threshold, and it can only hold that promise
       -- if there is exactly one place holding the numbers.
       CASE WHEN s.readiness_pct >= 85 THEN 'READY'
            WHEN s.readiness_pct >= 70 THEN 'AT_RISK'
            ELSE 'NOT_READY' END          AS readiness_band,
       g.limiting_dimension,
       g.limiting_dimension_name,
       g.limiting_score,
       g.limiting_weight
FROM (
    SELECT project_key,
           SUM(score_pct * weight_pct) * 1.0
               / NULLIF(SUM(weight_pct), 0) AS readiness_pct,
           COUNT(*)                         AS dimensions_assessed,
           MIN(assessed_on)                 AS oldest_assessment,
           MAX(assessed_on)                 AS newest_assessment
    FROM   tr_metric.v_project_readiness_dimension
    GROUP  BY project_key
) s
LEFT JOIN tr_metric.v_project_readiness_gap g USING (project_key);

-- The filterable register the console reads.
--
-- Deliberately NOT carrying completion_fiscal_year: readiness only exists for
-- work that has not completed, so a fiscal-year filter over it would return an
-- empty screen and look like a bug rather than a category error.
CREATE OR REPLACE VIEW tr_mart.mart_readiness_register AS
SELECT r.project_key,
       p.project_id,
       p.project_name,
       p.transfer_type,
       p.complexity_class,
       p.portfolio,
       p.source_site,
       p.target_site,
       p.status,
       reg.health,
       reg.schedule_deviation_days,
       r.readiness_pct,
       r.readiness_band,
       r.dimensions_assessed,
       r.limiting_dimension,
       r.limiting_dimension_name,
       r.limiting_score,
       r.newest_assessment,
       -- Measured against the warehouse vintage, not CURRENT_DATE, so a readiness
       -- age printed in last week's report still recomputes to the same number.
       ((SELECT data_as_of FROM tr_metric.v_data_vintage) - r.newest_assessment)
                                            AS assessment_age_days
FROM   tr_metric.v_project_readiness r
JOIN   tr_core.dim_project           p   USING (project_key)
LEFT JOIN tr_mart.mart_project_register reg USING (project_key);

-- Portfolio-level readiness by dimension: which dimension is holding the whole
-- portfolio back, not just one project. This is what turns "qualification is the
-- bottleneck" from an assertion in a narrative into a number on a screen.
CREATE OR REPLACE VIEW tr_mart.mart_readiness_dimension AS
SELECT d.dimension_code,
       d.dimension_name,
       d.weight_pct,
       d.sequence_no,
       p.transfer_type,
       p.portfolio,
       p.complexity_class,
       p.source_site,
       p.target_site,
       d.score_pct,
       d.project_key
FROM   tr_metric.v_project_readiness_dimension d
JOIN   tr_core.dim_project                     p USING (project_key);


-- ---- 2. Transfer network intelligence -------------------------------------

-- Median time in each lifecycle stage, per lane. The input is the registered
-- STAGE_CYCLE_TIME metric; this only changes the grain it is read at.
CREATE OR REPLACE VIEW tr_mart.mart_route_stage AS
SELECT p.source_site,
       p.target_site,
       s.from_stage,
       s.to_stage,
       s.from_seq,
       COUNT(*)                                       AS n_projects,
       PERCENTILE_CONT(0.50) WITHIN GROUP (
           ORDER BY s.stage_cycle_time_days)          AS median_stage_days
FROM   tr_metric.v_stage_cycle_time s
JOIN   tr_core.dim_project          p USING (project_key)
GROUP  BY p.source_site, p.target_site, s.from_stage, s.to_stage, s.from_seq;

-- ROUTE_BOTTLENECK_STAGE: the slowest stage on each lane.
CREATE OR REPLACE VIEW tr_mart.mart_route_bottleneck AS
SELECT source_site,
       target_site,
       from_stage        AS bottleneck_stage,
       to_stage          AS bottleneck_next_stage,
       median_stage_days AS bottleneck_median_days,
       n_projects        AS bottleneck_n_projects
FROM (
    SELECT ms.*,
           ROW_NUMBER() OVER (PARTITION BY ms.source_site, ms.target_site
                              ORDER BY ms.median_stage_days DESC,
                                       ms.from_seq ASC) AS rn
    FROM   tr_mart.mart_route_stage ms
) ranked
WHERE rn = 1;

-- One row per source->target lane.
--
-- Every column here is an existing registered metric re-grained; none of them is
-- a new definition. Lead time is ACTUAL_TRANSFER_CYCLE_TIME, the rate is
-- ON_TIME_COMPLETION_RATE, the drift is BASELINE_FINISH_DEVIATION_DAYS. That is
-- the point of a semantic layer: a new question should cost a GROUP BY, not a
-- new definition of "on time" that disagrees with the old one by a day.
CREATE OR REPLACE VIEW tr_mart.mart_transfer_network AS
SELECT r.source_site,
       r.target_site,
       COUNT(*)                                        AS total_transfers,
       COUNT(*) FILTER (WHERE r.status = 'ACTIVE')     AS active_transfers,
       COUNT(*) FILTER (WHERE r.status = 'COMPLETED')  AS completed_transfers,
       COUNT(*) FILTER (WHERE r.status = 'PLANNED')    AS planned_transfers,
       PERCENTILE_CONT(0.50) WITHIN GROUP (
           ORDER BY r.actual_cycle_time_days)          AS median_lead_time_days,
       -- Counted over the population the metric is defined for, never over every
       -- row on the lane: an in-flight project carries a NULL on_time, and an
       -- ELSE 0 here would score every unfinished transfer as a miss.
       100.0 * COUNT(*) FILTER (WHERE r.on_time)
             / NULLIF(COUNT(*) FILTER (WHERE r.on_time IS NOT NULL), 0)
                                                       AS on_time_rate,
       PERCENTILE_CONT(0.50) WITHIN GROUP (
           ORDER BY r.schedule_deviation_days)         AS median_schedule_deviation_days,
       AVG(rd.readiness_pct)                           AS avg_readiness_pct,
       COUNT(*) FILTER (WHERE r.health = 'LATE')       AS late_transfers,
       MAX(bn.bottleneck_stage)                        AS bottleneck_stage,
       MAX(bn.bottleneck_median_days)                  AS bottleneck_median_days
FROM   tr_mart.mart_project_register    r
LEFT JOIN tr_metric.v_project_readiness rd USING (project_key)
LEFT JOIN tr_mart.mart_route_bottleneck bn
       ON bn.source_site = r.source_site AND bn.target_site = r.target_site
GROUP  BY r.source_site, r.target_site;

-- Per-site totals, so the network screen can size a node without the browser
-- summing lanes -- which would be the console recomputing a metric again.
CREATE OR REPLACE VIEW tr_mart.mart_site_flow AS
SELECT site, direction, SUM(total_transfers) AS transfers,
       SUM(active_transfers) AS active_transfers
FROM (
    SELECT source_site AS site, 'OUTBOUND' AS direction,
           total_transfers, active_transfers
    FROM   tr_mart.mart_transfer_network
    UNION ALL
    SELECT target_site, 'INBOUND', total_transfers, active_transfers
    FROM   tr_mart.mart_transfer_network
) f
GROUP BY site, direction;


-- ---- 3. Historical similarity ---------------------------------------------

-- TRANSFER_SIMILARITY_SCORE.
--
-- Deterministic and additive, so the score decomposes: the console can show that
-- two transfers matched on type and target site but not on complexity, and a
-- manager can disagree with the weighting on the evidence. An embedding would
-- retrieve comparable neighbours and be unable to answer "why is this one here?",
-- which is the question that gets asked the moment a recommendation is unwelcome.
--
-- The weights sit in SQL rather than in a table, unlike the readiness weights,
-- and the distinction is deliberate: readiness weighting is a business rule the
-- business renegotiates, while this is retrieval tuning. Promoting it to data
-- would invite it to be edited by people who have no way to evaluate the change.
--
-- Both sides of the join read tr_core.dim_project, so RLS scopes them both: a
-- manager entitled to one portfolio is compared only against history from that
-- portfolio. Similarity cannot become a side channel onto projects the caller
-- was never allowed to enumerate.
CREATE OR REPLACE VIEW tr_metric.v_transfer_similarity AS
SELECT a.project_key,
       b.project_key AS similar_project_key,
       CASE WHEN a.transfer_type    = b.transfer_type    THEN 35 ELSE 0 END
     + CASE WHEN a.complexity_class = b.complexity_class THEN 20 ELSE 0 END
     + CASE WHEN a.portfolio        = b.portfolio        THEN 20 ELSE 0 END
     + CASE WHEN a.target_site      = b.target_site      THEN 15 ELSE 0 END
     + CASE WHEN a.source_site      = b.source_site      THEN 10 ELSE 0 END
                                                    AS similarity_pct,
       CASE WHEN a.transfer_type    = b.transfer_type    THEN TRUE ELSE FALSE END AS match_transfer_type,
       CASE WHEN a.complexity_class = b.complexity_class THEN TRUE ELSE FALSE END AS match_complexity,
       CASE WHEN a.portfolio        = b.portfolio        THEN TRUE ELSE FALSE END AS match_portfolio,
       CASE WHEN a.target_site      = b.target_site      THEN TRUE ELSE FALSE END AS match_target_site,
       CASE WHEN a.source_site      = b.source_site      THEN TRUE ELSE FALSE END AS match_source_site
FROM   tr_core.dim_project a
CROSS JOIN tr_core.dim_project b
WHERE  a.status IN ('ACTIVE', 'PLANNED')
  AND  b.status = 'COMPLETED'
  AND  b.actual_finish IS NOT NULL
  AND  a.project_key <> b.project_key;

-- Similarity decorated with what actually happened to the reference transfer.
-- The score alone is trivia; the score next to "this one finished 28 days late"
-- is the thing worth putting in front of a manager.
CREATE OR REPLACE VIEW tr_mart.mart_similar_transfers AS
SELECT s.project_key,
       s.similar_project_key,
       s.similarity_pct,
       s.match_transfer_type,
       s.match_complexity,
       s.match_portfolio,
       s.match_target_site,
       s.match_source_site,
       ref.project_id             AS similar_project_id,
       ref.project_name           AS similar_project_name,
       ref.transfer_type,
       ref.complexity_class,
       ref.portfolio,
       ref.source_site,
       ref.target_site,
       ref.actual_cycle_time_days,
       ref.completion_variance_days,
       ref.on_time,
       ref.health,
       ref.completion_fiscal_year
FROM   tr_metric.v_transfer_similarity s
JOIN   tr_mart.mart_project_register ref
       ON ref.project_key = s.similar_project_key
WHERE  s.similarity_pct > 0;
