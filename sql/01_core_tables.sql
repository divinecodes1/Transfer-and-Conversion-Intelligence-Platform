-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 01_core_tables.sql
-- Canonical CORE model. The single most important design decision (per the
-- architecture spec) is to PRESERVE HISTORY EXPLICITLY:
--   * FACT_SCHEDULE_REVISION  -> immutable baseline + every replan  (original vs latest)
--   * FACT_PROJECT_SNAPSHOT   -> project state as known on each date (forecast accuracy)
-- Without these, "original schedule vs latest schedule" and forecast-error
-- analytics are impossible because the past is overwritten.
--
-- Surrogate keys are assigned by the loader (Python), so this DDL uses plain
-- INTEGER PKs and stays portable across PostgreSQL and DuckDB (no SERIAL).
-- ============================================================================

-- CASCADE so a rebuild is repeatable: PostgreSQL refuses to drop a table that
-- a view still depends on, and after the first successful run every metric view
-- (03) and mart (04) is bound to these tables. Everything CASCADE removes here
-- is derived and recreated later in the same run. DuckDB accepts the same
-- syntax, so both engines keep sharing one set of SQL files.
DROP TABLE IF EXISTS tr_core.fact_milestone_event CASCADE;
DROP TABLE IF EXISTS tr_core.fact_schedule_revision CASCADE;
DROP TABLE IF EXISTS tr_core.fact_project_snapshot CASCADE;
DROP TABLE IF EXISTS tr_core.dim_milestone CASCADE;
DROP TABLE IF EXISTS tr_core.dim_fiscal_date CASCADE;
DROP TABLE IF EXISTS tr_core.dim_project CASCADE;

-- ---- Dimensions -----------------------------------------------------------

CREATE TABLE tr_core.dim_project (
    project_key      INTEGER PRIMARY KEY,
    project_id       VARCHAR NOT NULL,          -- business id, e.g. T-017
    project_name     VARCHAR,
    transfer_type    VARCHAR,                   -- FAB_TO_FAB | INT_TO_FOUNDRY | ...
    complexity_class VARCHAR,                   -- LOW | MED | HIGH
    source_site      VARCHAR,
    target_site      VARCHAR,
    portfolio        VARCHAR,                   -- PF_AUTO | PF_POWER | PF_IOT
    status           VARCHAR,                   -- PLANNED | ACTIVE | COMPLETED | CANCELLED
    actual_start     DATE,
    actual_finish    DATE
);

CREATE TABLE tr_core.dim_milestone (
    milestone_key   INTEGER PRIMARY KEY,
    milestone_code  VARCHAR NOT NULL,
    milestone_name  VARCHAR,
    sequence_no     INTEGER
);

CREATE TABLE tr_core.dim_fiscal_date (
    calendar_date   DATE PRIMARY KEY,
    fiscal_week     INTEGER,
    fiscal_month    INTEGER,
    fiscal_quarter  INTEGER,
    fiscal_year     INTEGER                     -- Infineon FY starts 1 October
);

-- ---- Facts ----------------------------------------------------------------

-- One row per milestone reached/planned per project.
CREATE TABLE tr_core.fact_milestone_event (
    project_key   INTEGER NOT NULL,
    milestone_key INTEGER NOT NULL,
    planned_date  DATE,
    actual_date   DATE,
    event_status  VARCHAR                       -- PLANNED | REACHED
);

-- Immutable baseline (is_baseline = TRUE) plus every subsequent replan.
-- "Original schedule" = the baseline row; "latest schedule" = newest revision.
CREATE TABLE tr_core.fact_schedule_revision (
    project_key       INTEGER NOT NULL,
    revision_id       INTEGER NOT NULL,
    revision_timestamp TIMESTAMP,
    revision_reason   VARCHAR,
    planned_start     DATE,
    planned_finish    DATE,
    forecast_finish   DATE,
    is_baseline       BOOLEAN
);

-- Point-in-time project state. Lets us answer "what did we believe on 2026-03-01?"
CREATE TABLE tr_core.fact_project_snapshot (
    project_key     INTEGER NOT NULL,
    snapshot_date   DATE,
    status          VARCHAR,
    forecast_finish DATE,
    current_stage   VARCHAR,
    risk_status     VARCHAR,                    -- GREEN | AMBER | RED
    progress_pct    DOUBLE PRECISION
);
