-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 10_rls.sql   (PostgreSQL only)
-- Row-level security on the canonical project dimension.
--
-- Why here and not in the API: a workbook filter is not a security boundary, and
-- neither is an application WHERE clause on its own. Enforcing at the table means
-- the same rule holds for the dashboards, the API, the assistant, and anyone with
-- a psql prompt. The application layer is defence in depth on top, not the fence.
--
-- Everything the platform serves reaches project rows through tr_core.dim_project
-- -- every metric view either selects from it or joins it -- so one policy here
-- scopes the whole metric and mart layer rather than needing a policy per view.
--
-- THREE things have to be true together, and any one of them missing makes the
-- policy look installed while enforcing nothing:
--
--   1. FORCE ROW LEVEL SECURITY, or the table owner bypasses its own policy.
--   2. A NON-SUPERUSER connection, because superusers bypass RLS unconditionally
--      -- which is why the API gets its own least-privilege reader role below
--      rather than reusing the bootstrap account that owns the schema.
--   3. security_invoker on every view, or a view owned by the schema owner
--      evaluates the policy as *its owner* and quietly returns everything.
--
-- The scope is carried in a session setting that the API sets per request from
-- the caller's resolved entitlements. It is FAIL-CLOSED: an unset scope selects
-- no rows, so forgetting to set it produces an obviously empty result rather than
-- a quiet full-portfolio disclosure. The ETL sets '*' explicitly.
-- ============================================================================

ALTER TABLE tr_core.dim_project ENABLE ROW LEVEL SECURITY;
ALTER TABLE tr_core.dim_project FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS project_portfolio_scope ON tr_core.dim_project;

CREATE POLICY project_portfolio_scope ON tr_core.dim_project
FOR SELECT
USING (
    current_setting('transferops.portfolios', true) = '*'
    OR portfolio = ANY (
        string_to_array(
            coalesce(current_setting('transferops.portfolios', true), ''), ',')
    )
);

-- Writes stay with the loader, which runs with the scope set to '*'.
DROP POLICY IF EXISTS project_write ON tr_core.dim_project;

CREATE POLICY project_write ON tr_core.dim_project
FOR ALL
USING (current_setting('transferops.portfolios', true) = '*')
WITH CHECK (current_setting('transferops.portfolios', true) = '*');


-- ---- The application's least-privilege identity ----------------------------
-- The bootstrap account owns the schema and is a superuser, so it can never be
-- subject to RLS. The API therefore connects as this role instead: SELECT only,
-- no ownership, and explicitly NOBYPASSRLS.
-- The password is supplied by the loader as a session setting (see
-- etl/secrets.py), never written here. A credential committed to the repository
-- is a credential published with it, and rotating one would mean a code change.
DO $$
DECLARE
    pw TEXT := current_setting('transferops.reader_password', true);
BEGIN
    IF pw IS NULL OR pw = '' THEN
        RAISE EXCEPTION 'transferops.reader_password is not set; the loader must '
                        'supply it from TRANSFEROPS_READER_PASSWORD';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'transferops_reader') THEN
        EXECUTE format('CREATE ROLE transferops_reader LOGIN PASSWORD %L', pw);
    ELSE
        -- Rebuilding an existing warehouse re-applies the current password, so
        -- rotation is a redeploy rather than a manual step someone forgets.
        EXECUTE format('ALTER ROLE transferops_reader LOGIN PASSWORD %L', pw);
    END IF;
END
$$;

ALTER ROLE transferops_reader NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT USAGE ON SCHEMA tr_core, tr_metric, tr_mart, tr_gov TO transferops_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA tr_core, tr_metric, tr_mart, tr_gov
    TO transferops_reader;


-- ---- Make every view evaluate as its caller --------------------------------
-- Without this, a view owned by the schema owner runs the underlying policy with
-- the OWNER's rights, and the reader role sees the whole portfolio through it.
-- Applied dynamically so a view added later cannot silently miss the setting.
DO $$
DECLARE
    v record;
BEGIN
    FOR v IN
        SELECT schemaname, viewname
        FROM   pg_views
        WHERE  schemaname IN ('tr_metric', 'tr_mart', 'tr_stg')
    LOOP
        EXECUTE format('ALTER VIEW %I.%I SET (security_invoker = true)',
                       v.schemaname, v.viewname);
    END LOOP;
END
$$;
