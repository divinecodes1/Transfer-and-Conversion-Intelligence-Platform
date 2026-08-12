-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 02_governance.sql
-- Every metric is a GOVERNED PRODUCT: one definition, one owner, one version.
-- This is what stops "five different definitions of cycle time" and what the
-- AI agent later queries instead of inventing what "delay" means.
-- ============================================================================

DROP TABLE IF EXISTS tr_gov.metric_definition;

CREATE TABLE tr_gov.metric_definition (
    metric_code    VARCHAR PRIMARY KEY,
    business_name  VARCHAR NOT NULL,
    definition     VARCHAR NOT NULL,
    grain          VARCHAR,
    unit           VARCHAR,
    population      VARCHAR,
    exclusions     VARCHAR,
    owner          VARCHAR,
    version        VARCHAR,
    effective_from DATE
);

INSERT INTO tr_gov.metric_definition
(metric_code, business_name, definition, grain, unit, population, exclusions, owner, version, effective_from) VALUES
('ACTUAL_TRANSFER_CYCLE_TIME','Actual Cycle Time',
 'actual_finish - actual_start','Project','days',
 'Completed transfer projects','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('FORECAST_CYCLE_TIME','Forecast Cycle Time',
 'forecast_finish - actual_start','Project/snapshot','days',
 'Transfer projects with a started actual and a forecast snapshot','Cancelled projects','Transfer Management','1.0','2026-10-01'),

-- Population deliberately spans open AND completed projects: the original-vs-latest
-- chart is read both ways ("how far has the plan moved?" while running, "how far did
-- it move?" afterwards), and the golden case T-017 asserts it on a completed project.
('BASELINE_FINISH_DEVIATION_DAYS','Baseline Finish Deviation',
 'latest_planned_finish - baseline_finish','Project','days',
 'Transfer projects with a valid baseline','Cancelled projects','Transfer Management','1.2','2026-10-01'),

('COMPLETION_VARIANCE_DAYS','Completion Variance',
 'actual_finish - baseline_finish','Completed project','days',
 'Completed transfer projects with a valid baseline','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('FORECAST_ERROR_DAYS','Forecast Error',
 'actual_finish - forecast_finish_as_of_snapshot','Completed project/horizon','days',
 'Completed projects with historical snapshots','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('TRANSFER_THROUGHPUT','Throughput',
 'count of projects completed in a fiscal period','Portfolio/period','count',
 'Completed transfer projects','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('ON_TIME_COMPLETION_RATE','On-Time Completion Rate',
 'projects completed on/before baseline finish / completed projects','Portfolio/period','ratio',
 'Completed transfer projects with a valid baseline','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('STAGE_CYCLE_TIME','Stage Cycle Time',
 'actual_date(milestone_n+1) - actual_date(milestone_n)','Project/stage','days',
 'Projects that reached both milestones','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('CYCLE_TIME_DISTRIBUTION','Cycle-Time Distribution',
 'P25/P50/P75/P90 of actual cycle time','Segment/period','days',
 'Completed transfer projects','Cancelled projects','Transfer Management','1.0','2026-10-01'),

-- The three below are what the portfolio KPI tiles read. They are registered here
-- for the same reason as everything else: a tile that invents "replan rate" in the
-- browser is a fifth definition of it, and the browser is the one place nobody
-- diffs. Each has exactly one implementation, bound in tests/governance_checks.py.
('REPLAN_RATE','Replan Rate',
 'projects with more than one schedule revision / projects','Portfolio/period','ratio',
 'Transfer projects with a valid baseline','Cancelled projects','Transfer Management','1.0','2026-10-01'),

('WIP_AGE_DAYS','WIP Age',
 'current_date - actual_start for projects still in flight','Project','days',
 'Started transfer projects with no actual finish','Cancelled projects, projects not yet started','Transfer Management','1.0','2026-10-01'),

('PORTFOLIO_WIP','Work in Progress',
 'count of transfer projects started and not yet finished','Portfolio','count',
 'Started transfer projects with no actual finish','Cancelled projects','Transfer Management','1.0','2026-10-01');
