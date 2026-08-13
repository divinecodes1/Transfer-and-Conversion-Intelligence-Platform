-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 06_staging.sql
-- The typed layer. Answers the second question:
--
--     "What does the source MEAN, after typing, standardisation and dedup?"
--
-- Keeping this separate from RAW is what makes a data-quality complaint
-- tractable. When a number looks wrong, the question "did the source send it
-- wrong, or did we transform it wrong?" is answerable by diffing two layers
-- instead of by arguing.
--
-- Three things happen here and nowhere else:
--
--   TYPING           strings become dates, integers and booleans. Values that
--                    cannot be typed become NULL rather than failing the batch --
--                    the ingestion tier has already recorded them as rejects, and
--                    one malformed row should not stop a portfolio from loading.
--   STANDARDISATION  trimming and case-folding, so 'completed', ' COMPLETED '
--                    and 'Completed' stop being three different statuses.
--   DEDUPLICATION    redelivery is normal in enterprise feeds. The newest row per
--                    business key wins, and an unchanged redelivery collapses to
--                    the same record_hash rather than doubling a project.
--
-- Views rather than tables: staging holds no state of its own, so it can never
-- drift from what RAW currently contains.
--
-- This file is byte-identical on both engines. The safe-cast helpers it relies on
-- are defined per engine in 06_functions_duckdb.sql / 06_functions_postgres.sql,
-- because DuckDB's TRY_CAST has no PostgreSQL equivalent -- one small shim beats
-- two copies of the staging logic drifting apart.
-- ============================================================================

DROP VIEW IF EXISTS tr_stg.stg_project;
DROP VIEW IF EXISTS tr_stg.stg_schedule;
DROP VIEW IF EXISTS tr_stg.stg_milestone;
DROP VIEW IF EXISTS tr_stg.stg_snapshot;

CREATE VIEW tr_stg.stg_project AS
SELECT project_key, project_id, project_name, transfer_type, complexity_class,
       source_site, target_site, portfolio, product_line, application_segment,
       status, actual_start, actual_finish,
       batch_id, record_hash
FROM (
    SELECT
        tr_stg.to_int_safe(project_key)                    AS project_key,
        UPPER(TRIM(project_id))                            AS project_id,
        TRIM(project_name)                                 AS project_name,
        UPPER(TRIM(transfer_type))                         AS transfer_type,
        UPPER(TRIM(complexity_class))                      AS complexity_class,
        TRIM(source_site)                                  AS source_site,
        TRIM(target_site)                                  AS target_site,
        UPPER(TRIM(portfolio))                             AS portfolio,
        UPPER(TRIM(product_line))                          AS product_line,
        UPPER(TRIM(application_segment))                   AS application_segment,
        UPPER(TRIM(status))                                AS status,
        tr_stg.to_date_safe(actual_start)                  AS actual_start,
        tr_stg.to_date_safe(actual_finish)                 AS actual_finish,
        batch_id, record_hash,
        ROW_NUMBER() OVER (PARTITION BY TRIM(project_key)
                           ORDER BY ingested_at DESC, record_hash) AS rn
    FROM tr_raw.raw_project
) d
WHERE rn = 1
  AND project_key IS NOT NULL
  AND project_id  IS NOT NULL;

CREATE VIEW tr_stg.stg_schedule AS
SELECT project_key, revision_id, revision_timestamp, revision_reason,
       planned_start, planned_finish, forecast_finish, is_baseline,
       batch_id, record_hash
FROM (
    SELECT
        tr_stg.to_int_safe(project_key)                     AS project_key,
        tr_stg.to_int_safe(revision_id)                     AS revision_id,
        tr_stg.to_timestamp_safe(revision_timestamp)        AS revision_timestamp,
        UPPER(TRIM(revision_reason))                        AS revision_reason,
        tr_stg.to_date_safe(planned_start)                  AS planned_start,
        tr_stg.to_date_safe(planned_finish)                 AS planned_finish,
        tr_stg.to_date_safe(forecast_finish)                AS forecast_finish,
        UPPER(TRIM(is_baseline)) IN ('TRUE', 'T', '1', 'Y') AS is_baseline,
        batch_id, record_hash,
        ROW_NUMBER() OVER (PARTITION BY TRIM(project_key), TRIM(revision_id)
                           ORDER BY ingested_at DESC, record_hash) AS rn
    FROM tr_raw.raw_schedule
) d
WHERE rn = 1
  AND project_key IS NOT NULL
  AND revision_id IS NOT NULL;

CREATE VIEW tr_stg.stg_milestone AS
SELECT project_key, milestone_key, planned_date, actual_date, event_status,
       batch_id, record_hash
FROM (
    SELECT
        tr_stg.to_int_safe(project_key)                   AS project_key,
        tr_stg.to_int_safe(milestone_key)                 AS milestone_key,
        tr_stg.to_date_safe(planned_date)                 AS planned_date,
        tr_stg.to_date_safe(actual_date)                  AS actual_date,
        UPPER(TRIM(event_status))                          AS event_status,
        batch_id, record_hash,
        ROW_NUMBER() OVER (PARTITION BY TRIM(project_key), TRIM(milestone_key)
                           ORDER BY ingested_at DESC, record_hash) AS rn
    FROM tr_raw.raw_milestone
) d
WHERE rn = 1
  AND project_key   IS NOT NULL
  AND milestone_key IS NOT NULL;

CREATE VIEW tr_stg.stg_snapshot AS
SELECT project_key, snapshot_date, status, forecast_finish, current_stage,
       risk_status, progress_pct, batch_id, record_hash
FROM (
    SELECT
        tr_stg.to_int_safe(project_key)                     AS project_key,
        tr_stg.to_date_safe(snapshot_date)                  AS snapshot_date,
        UPPER(TRIM(status))                                 AS status,
        tr_stg.to_date_safe(forecast_finish)                AS forecast_finish,
        UPPER(TRIM(current_stage))                          AS current_stage,
        UPPER(TRIM(risk_status))                            AS risk_status,
        tr_stg.to_double_safe(progress_pct)                 AS progress_pct,
        batch_id, record_hash,
        -- One snapshot per project per day is the grain; a redelivery of the same
        -- day must replace, not accumulate.
        ROW_NUMBER() OVER (PARTITION BY TRIM(project_key), TRIM(snapshot_date)
                           ORDER BY ingested_at DESC, record_hash) AS rn
    FROM tr_raw.raw_snapshot
) d
WHERE rn = 1
  AND project_key   IS NOT NULL
  AND snapshot_date IS NOT NULL;
