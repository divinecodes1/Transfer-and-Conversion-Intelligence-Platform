-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 07_indexes.sql   (PostgreSQL only)
-- Access paths for the metric layer.
--
-- The core tables carried nothing but primary keys, so every join in
-- 03_metric_views.sql resolved by sequential scan. At this portfolio's size that
-- is invisible -- 904 revisions and 3,694 snapshots fit in memory and a seq scan
-- is genuinely the right plan. It stops being invisible at production volume,
-- and the point of this file is that the access paths are part of the design
-- rather than something discovered later under load.
--
-- Indexes are built AFTER the bulk load, which is both faster to build and the
-- order a real refresh would use. They are dropped implicitly with their tables
-- on every rebuild, so this file is idempotent by construction; IF NOT EXISTS
-- covers the layered path, which reruns it against surviving tables.
--
-- DuckDB deliberately does not run this. It is the dev/test engine, it is
-- columnar, and index maintenance there would cost more than the scans it saves.
-- ============================================================================

-- ---- The schedule history: joined by every schedule-derived metric ---------

-- v_baseline_schedule and v_latest_schedule both start here, and v_project_kpi
-- joins both. This is the single most-traversed edge in the model.
CREATE INDEX IF NOT EXISTS fact_schedule_revision_project
    ON tr_core.fact_schedule_revision (project_key);

-- The frozen baseline is one row in a few per project. A partial index means the
-- lookup touches only baseline rows instead of filtering every revision.
CREATE INDEX IF NOT EXISTS fact_schedule_revision_baseline
    ON tr_core.fact_schedule_revision (project_key)
    WHERE is_baseline;

-- v_latest_schedule takes the newest revision per project via ROW_NUMBER() over
-- exactly this ordering, so the index supplies the sort the window needs.
CREATE INDEX IF NOT EXISTS fact_schedule_revision_latest
    ON tr_core.fact_schedule_revision (project_key, revision_timestamp DESC, revision_id DESC);

-- ---- Snapshots: forecast accuracy, and the data-vintage probe --------------
CREATE INDEX IF NOT EXISTS fact_project_snapshot_project
    ON tr_core.fact_project_snapshot (project_key);

-- Every provenance envelope reports MAX(snapshot_date); this makes that a
-- backwards index scan rather than a full pass over the snapshot history.
CREATE INDEX IF NOT EXISTS fact_project_snapshot_date
    ON tr_core.fact_project_snapshot (snapshot_date);

-- ---- Milestones: stage cycle time joins the table to itself ---------------
CREATE INDEX IF NOT EXISTS fact_milestone_event_project
    ON tr_core.fact_milestone_event (project_key, milestone_key);

-- ---- The project dimension ------------------------------------------------

-- The row-level policy filters on portfolio on every single read, so this is the
-- access path the security model itself depends on.
CREATE INDEX IF NOT EXISTS dim_project_portfolio
    ON tr_core.dim_project (portfolio);

-- GET /projects/{project_id} looks projects up by business key, not surrogate.
CREATE INDEX IF NOT EXISTS dim_project_business_id
    ON tr_core.dim_project (project_id);

-- Most metric populations are "completed" or "not cancelled".
CREATE INDEX IF NOT EXISTS dim_project_status
    ON tr_core.dim_project (status);

-- ---- Give the planner current statistics ----------------------------------
-- Without this the tables were just bulk-loaded and carry no stats, so the first
-- queries after a refresh are planned against guesses.
ANALYZE tr_core.dim_project;
ANALYZE tr_core.fact_schedule_revision;
ANALYZE tr_core.fact_project_snapshot;
ANALYZE tr_core.fact_milestone_event;
