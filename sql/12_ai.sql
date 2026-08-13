-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 12_ai.sql   (PostgreSQL only)
-- Where model output is kept.
--
-- Like 11_observability.sql these tables are CREATE TABLE IF NOT EXISTS rather
-- than DROP/CREATE, but for a different reason in each case. The run log is
-- history, and history a warehouse reload erases is not history. The insight
-- cache and the risk scores are not history -- they are derived from a warehouse
-- vintage, and a reload produces a new one -- so they carry the vintage they were
-- generated against and are served only while that vintage still stands.
--
-- Three properties this file is responsible for:
--
--   * Model output is entitlement-scoped like everything else. A risk score names
--     a project, and a narrative names sites and slipping projects by name, so
--     both are readable only within the caller's portfolio scope. project_risk
--     reaches the policy the same way every metric view does -- through
--     tr_core.dim_project -- and insight carries its own policy on the portfolio
--     it was generated for.
--
--   * The writer is not the reader. `transferops_ai` may write these three tables
--     and nothing else; it holds no SELECT anywhere in tr_core, tr_metric or
--     tr_mart, because the refresh job reads its numbers through the governed API
--     under a resolved identity, never straight out of the warehouse. A
--     compromised generator can write a bad narrative -- it cannot read a project.
--
--   * Nothing here is a metric. No row in these tables is registered in
--     tr_gov.metric_definition, and tests/ai_checks.py asserts that stays true.
-- ============================================================================

-- ---- Cached narratives ----------------------------------------------------
-- One row per (kind, scope). The scope key is the filter set the narrative was
-- written for, so a briefing about PF_AUTO in FY26 is never shown for a different
-- scope -- the failure mode that makes a cached AI summary actively misleading
-- rather than merely stale.
CREATE TABLE IF NOT EXISTS tr_ai.insight (
    kind          VARCHAR NOT NULL,     -- portfolio_overview | report_summary | anomaly_watch
    scope_key     VARCHAR NOT NULL,     -- canonical serialisation of the filters
    portfolio     VARCHAR,              -- NULL = all portfolios; drives the policy below
    filters       JSONB   NOT NULL DEFAULT '{}'::jsonb,
    headline      VARCHAR,
    content       TEXT    NOT NULL,
    highlights    JSONB   NOT NULL DEFAULT '[]'::jsonb,
    model         VARCHAR,
    provider      VARCHAR,
    data_as_of    DATE,                 -- the warehouse vintage it describes
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (kind, scope_key)
);

CREATE INDEX IF NOT EXISTS insight_expires_at ON tr_ai.insight (expires_at);

-- ---- Per-project delay risk ----------------------------------------------
-- A score, a band, a predicted slip and the evidence the model said it used.
-- `drivers` and `rationale` are not decoration: a risk number nobody can argue
-- with is a risk number nobody will act on, and the whole reason this is kept
-- next to the governed register is so a reader can check the claim against it.
CREATE TABLE IF NOT EXISTS tr_ai.project_risk (
    project_key         INTEGER PRIMARY KEY,
    risk_score          INTEGER NOT NULL,     -- 0-100
    risk_band           VARCHAR NOT NULL,     -- low | medium | high
    predicted_slip_days INTEGER,
    drivers             JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale           VARCHAR,
    model               VARCHAR,
    provider            VARCHAR,
    data_as_of          DATE,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- Automation history ---------------------------------------------------
-- Every scheduled or manual refresh, whether it worked, and what it cost. This
-- is the table the automation screen reads. A nightly job with no visible run
-- history is a job that has been failing for a fortnight.
CREATE TABLE IF NOT EXISTS tr_ai.run_log (
    run_id        BIGSERIAL PRIMARY KEY,
    job           VARCHAR NOT NULL,     -- insight_refresh | risk_refresh
    status        VARCHAR NOT NULL,     -- running | success | failed | skipped
    trigger       VARCHAR,              -- cron | manual
    item_count    INTEGER NOT NULL DEFAULT 0,
    scopes        JSONB   NOT NULL DEFAULT '[]'::jsonb,
    detail        VARCHAR,
    error_message VARCHAR,
    model         VARCHAR,
    provider      VARCHAR,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    duration_ms   INTEGER
);

CREATE INDEX IF NOT EXISTS run_log_started_at ON tr_ai.run_log (started_at DESC);

-- ---- The generator's identity ---------------------------------------------
-- Supplied by the loader from TRANSFEROPS_AI_PASSWORD, never written here, for
-- the same reason as every other role in this repository: a credential committed
-- to the repository is a credential published with it.
DO $$
DECLARE
    pw TEXT := current_setting('transferops.ai_password', true);
BEGIN
    IF pw IS NULL OR pw = '' THEN
        RAISE EXCEPTION 'transferops.ai_password is not set; the loader must '
                        'supply it from TRANSFEROPS_AI_PASSWORD';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'transferops_ai') THEN
        EXECUTE format('CREATE ROLE transferops_ai LOGIN PASSWORD %L', pw);
    ELSE
        EXECUTE format('ALTER ROLE transferops_ai LOGIN PASSWORD %L', pw);
    END IF;
END
$$;

DO $$
BEGIN
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        ALTER ROLE transferops_ai NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA tr_ai TO transferops_ai, transferops_reader;

-- Write here and nowhere else. Note the absence of any GRANT on tr_core,
-- tr_metric or tr_mart: the generator has no route to a project row at all.
GRANT SELECT, INSERT, UPDATE, DELETE ON tr_ai.insight, tr_ai.project_risk TO transferops_ai;
GRANT SELECT, INSERT, UPDATE ON tr_ai.run_log TO transferops_ai;
GRANT USAGE, SELECT ON SEQUENCE tr_ai.run_log_run_id_seq TO transferops_ai;

-- The API serves these to the dashboards, read-only.
GRANT SELECT ON tr_ai.insight, tr_ai.project_risk, tr_ai.run_log TO transferops_reader;

-- ---- Entitlement scoping ---------------------------------------------------
-- Same session setting, same fail-closed default as tr_core.dim_project: an unset
-- scope reads nothing. project_risk is scoped by joining the register, so it
-- inherits the one policy rather than declaring a second one that could drift;
-- insight is scoped on the portfolio it was written for.
ALTER TABLE tr_ai.insight      ENABLE ROW LEVEL SECURITY;
ALTER TABLE tr_ai.insight      FORCE  ROW LEVEL SECURITY;
ALTER TABLE tr_ai.project_risk ENABLE ROW LEVEL SECURITY;
ALTER TABLE tr_ai.project_risk FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS insight_portfolio_scope ON tr_ai.insight;
CREATE POLICY insight_portfolio_scope ON tr_ai.insight
FOR SELECT
USING (
    current_setting('transferops.portfolios', true) = '*'
    OR (portfolio IS NOT NULL AND portfolio = ANY (
            string_to_array(
                coalesce(current_setting('transferops.portfolios', true), ''), ',')))
);

DROP POLICY IF EXISTS insight_write ON tr_ai.insight;
CREATE POLICY insight_write ON tr_ai.insight
FOR ALL TO transferops_ai
USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS project_risk_scope ON tr_ai.project_risk;
CREATE POLICY project_risk_scope ON tr_ai.project_risk
FOR SELECT
USING (
    EXISTS (SELECT 1 FROM tr_core.dim_project p
            WHERE p.project_key = tr_ai.project_risk.project_key)
);

DROP POLICY IF EXISTS project_risk_write ON tr_ai.project_risk;
CREATE POLICY project_risk_write ON tr_ai.project_risk
FOR ALL TO transferops_ai
USING (true) WITH CHECK (true);
