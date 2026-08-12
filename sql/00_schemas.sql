-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 00_schemas.sql
-- Six-layer schema separation (the "renovation" the business owner asked for).
-- Replaces the typical failure mode of an accreted system:
--   TABLE_01 / VIEW_02 / VIEW_FINAL_NEW / VIEW_DASHBOARD_FIX / ...
-- with clean, purpose-named layers.
-- Portable across PostgreSQL and DuckDB.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS tr_raw;     -- source-faithful landing (exactly what the source delivered)
CREATE SCHEMA IF NOT EXISTS tr_stg;     -- typed / standardised / deduplicated
CREATE SCHEMA IF NOT EXISTS tr_core;    -- canonical project model + FULL HISTORY (revisions + snapshots)
CREATE SCHEMA IF NOT EXISTS tr_metric;  -- governed KPI logic, one definition per metric
CREATE SCHEMA IF NOT EXISTS tr_mart;    -- curated reporting marts for BI (Tableau/Superset consume these)
CREATE SCHEMA IF NOT EXISTS tr_gov;     -- governance: metric dictionary, ownership, versions
CREATE SCHEMA IF NOT EXISTS tr_ai;      -- model OUTPUT: cached narratives, risk scores, run history

-- tr_ai sits outside the metric layers on purpose. Everything in tr_metric and
-- tr_mart is derived by a rule someone can read; everything in tr_ai is derived by
-- a model, and the two must never be mistaken for one another. Nothing here is a
-- governed metric, nothing here is registered in tr_gov.metric_definition, and no
-- dashboard number is ever sourced from it -- a narrative *about* the numbers is
-- not one of the numbers.
