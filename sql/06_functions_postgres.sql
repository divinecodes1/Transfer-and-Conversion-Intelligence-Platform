-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 06_functions_postgres.sql   (PostgreSQL only)
-- The PostgreSQL half of the safe-cast helpers. Same four names, same
-- behaviour, so sql/06_staging.sql is byte-identical across both engines.
--
-- PostgreSQL has no TRY_CAST expression. The portable equivalent is a function
-- that traps the conversion error and returns NULL, which is exactly what the
-- staging layer wants: an unconvertible value becomes NULL here and has already
-- been recorded as a reject by the ingestion tier.
--
-- These are IMMUTABLE and STRICT-ish by construction so the planner can still
-- fold them; the exception block costs a subtransaction per bad row, which is
-- the right trade when bad rows are the exception rather than the rule.
-- ============================================================================

CREATE OR REPLACE FUNCTION tr_stg.to_date_safe(s TEXT) RETURNS DATE
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    RETURN NULLIF(BTRIM(s), '')::DATE;
EXCEPTION WHEN others THEN
    RETURN NULL;
END
$fn$;

CREATE OR REPLACE FUNCTION tr_stg.to_int_safe(s TEXT) RETURNS INTEGER
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    RETURN NULLIF(BTRIM(s), '')::INTEGER;
EXCEPTION WHEN others THEN
    RETURN NULL;
END
$fn$;

CREATE OR REPLACE FUNCTION tr_stg.to_timestamp_safe(s TEXT) RETURNS TIMESTAMP
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    RETURN NULLIF(BTRIM(s), '')::TIMESTAMP;
EXCEPTION WHEN others THEN
    RETURN NULL;
END
$fn$;

CREATE OR REPLACE FUNCTION tr_stg.to_double_safe(s TEXT) RETURNS DOUBLE PRECISION
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    RETURN NULLIF(BTRIM(s), '')::DOUBLE PRECISION;
EXCEPTION WHEN others THEN
    RETURN NULL;
END
$fn$;
