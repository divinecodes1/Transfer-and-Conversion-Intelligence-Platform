-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 05_raw_tables.sql
-- The landing layer. Answers exactly one question:
--
--     "What did the source actually deliver?"
--
-- Every column is VARCHAR on purpose. RAW's job is fidelity, not correctness --
-- if a date arrives as "2026-13-45" or a status as "  completed ", that is a fact
-- about the source and it must survive ingestion, because you cannot investigate
-- a data-quality complaint against a value that was silently coerced on the way
-- in. Typing, trimming and standardisation happen in STAGING, where they can be
-- inspected and reversed.
--
-- The operational metadata on every row is what makes an incident tractable:
-- which system sent it, which batch, when, and a content hash so a redelivery of
-- unchanged data is recognisable as such rather than becoming a duplicate.
-- ============================================================================

DROP TABLE IF EXISTS tr_raw.raw_project CASCADE;
DROP TABLE IF EXISTS tr_raw.raw_schedule CASCADE;
DROP TABLE IF EXISTS tr_raw.raw_milestone CASCADE;
DROP TABLE IF EXISTS tr_raw.raw_snapshot CASCADE;

CREATE TABLE tr_raw.raw_project (
    source_system    VARCHAR,
    source_record_id VARCHAR,
    ingested_at      TIMESTAMP,
    batch_id         VARCHAR,
    record_hash      VARCHAR,
    project_key      VARCHAR,
    project_id       VARCHAR,
    project_name     VARCHAR,
    transfer_type    VARCHAR,
    complexity_class VARCHAR,
    source_site      VARCHAR,
    target_site      VARCHAR,
    portfolio        VARCHAR,
    -- What is being moved, and who buys it. RAW lands them as delivered; the
    -- mapping to dim_product_line / dim_application is a CORE concern, so an
    -- unrecognised code is a fact about the source here rather than a reject.
    product_line        VARCHAR,
    application_segment VARCHAR,
    status           VARCHAR,
    actual_start     VARCHAR,
    actual_finish    VARCHAR
);

CREATE TABLE tr_raw.raw_schedule (
    source_system      VARCHAR,
    source_record_id   VARCHAR,
    ingested_at        TIMESTAMP,
    batch_id           VARCHAR,
    record_hash        VARCHAR,
    project_key        VARCHAR,
    revision_id        VARCHAR,
    revision_timestamp VARCHAR,
    revision_reason    VARCHAR,
    planned_start      VARCHAR,
    planned_finish     VARCHAR,
    forecast_finish    VARCHAR,
    is_baseline        VARCHAR
);

CREATE TABLE tr_raw.raw_milestone (
    source_system    VARCHAR,
    source_record_id VARCHAR,
    ingested_at      TIMESTAMP,
    batch_id         VARCHAR,
    record_hash      VARCHAR,
    project_key      VARCHAR,
    milestone_key    VARCHAR,
    planned_date     VARCHAR,
    actual_date      VARCHAR,
    event_status     VARCHAR
);

CREATE TABLE tr_raw.raw_snapshot (
    source_system    VARCHAR,
    source_record_id VARCHAR,
    ingested_at      TIMESTAMP,
    batch_id         VARCHAR,
    record_hash      VARCHAR,
    project_key      VARCHAR,
    snapshot_date    VARCHAR,
    status           VARCHAR,
    forecast_finish  VARCHAR,
    current_stage    VARCHAR,
    risk_status      VARCHAR,
    progress_pct     VARCHAR
);

-- Rejected rows are quarantined, never dropped. A row that fails validation is
-- the most informative row in the batch: it is the one someone has to look at.
DROP TABLE IF EXISTS tr_raw.quarantine CASCADE;

CREATE TABLE tr_raw.quarantine (
    batch_id      VARCHAR,
    quarantined_at TIMESTAMP,
    source_table  VARCHAR,
    tier          VARCHAR,      -- INGESTION | CORE | METRIC
    severity      VARCHAR,      -- REJECT (held back) | WARN (resolved downstream)
    check_name    VARCHAR,
    source_record_id VARCHAR,
    detail        VARCHAR
);
