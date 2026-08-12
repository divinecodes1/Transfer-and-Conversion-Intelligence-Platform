-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 06_functions_duckdb.sql   (DuckDB only)
-- Safe-cast helpers, so 06_staging.sql can be engine-neutral.
--
-- The staging layer needs "convert this string, and give me NULL if it isn't
-- convertible" -- a malformed date from an upstream system must become NULL and
-- be quarantined, not abort the batch. DuckDB spells that TRY_CAST; PostgreSQL
-- has no equivalent expression. Rather than fork the staging SQL and let two
-- copies drift, both engines expose the same four function names and the
-- staging file stays identical between them.
-- ============================================================================

CREATE OR REPLACE MACRO tr_stg.to_date_safe(s) AS
    TRY_CAST(NULLIF(TRIM(CAST(s AS VARCHAR)), '') AS DATE);

CREATE OR REPLACE MACRO tr_stg.to_int_safe(s) AS
    TRY_CAST(NULLIF(TRIM(CAST(s AS VARCHAR)), '') AS INTEGER);

CREATE OR REPLACE MACRO tr_stg.to_timestamp_safe(s) AS
    TRY_CAST(NULLIF(TRIM(CAST(s AS VARCHAR)), '') AS TIMESTAMP);

CREATE OR REPLACE MACRO tr_stg.to_double_safe(s) AS
    TRY_CAST(NULLIF(TRIM(CAST(s AS VARCHAR)), '') AS DOUBLE);
