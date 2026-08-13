-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 11_observability.sql   (PostgreSQL only)
-- Operational history for the platform itself.
--
-- Everything else in sql/ is rebuilt from source on every load -- that is what
-- makes the warehouse reproducible. These two tables are the deliberate
-- exception, so they are CREATE TABLE IF NOT EXISTS rather than DROP/CREATE:
-- an audit trail that is wiped whenever someone reloads the warehouse is not an
-- audit trail, and "when did loads last succeed?" cannot be answered by a table
-- that only remembers the current one.
--
-- The auditor role can INSERT into the audit table and nothing else. The
-- assistant runs read-only against the metric layer and writes only its own
-- provenance record, so a compromised assistant still cannot touch a metric.
-- ============================================================================

CREATE TABLE IF NOT EXISTS tr_gov.etl_run (
    run_id       BIGSERIAL PRIMARY KEY,
    engine       VARCHAR,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    duration_ms  INTEGER,
    rows_loaded  INTEGER,
    dq_passed    INTEGER,
    dq_failed    INTEGER,
    status       VARCHAR          -- SUCCESS | FAILED
);

CREATE TABLE IF NOT EXISTS tr_gov.agent_audit (
    call_id          BIGSERIAL PRIMARY KEY,
    asked_at         TIMESTAMPTZ DEFAULT now(),
    identity         VARCHAR,
    question         VARCHAR,
    intent           VARCHAR,
    resolved_metric  VARCHAR,
    metric_version   VARCHAR,
    filters          VARCHAR,
    tool_called      VARCHAR,
    rows_returned    INTEGER,
    duration_ms      INTEGER,
    abstained        BOOLEAN,
    provenance_complete BOOLEAN
    -- The question text is recorded; result rows deliberately are not. Provenance
    -- should be reconstructable without the audit log becoming a second copy of
    -- the data it was meant to govern access to.
);

CREATE INDEX IF NOT EXISTS agent_audit_asked_at ON tr_gov.agent_audit (asked_at);

-- Supplied by the loader, not committed. See etl/secrets.py.
DO $$
DECLARE
    pw TEXT := current_setting('transferops.auditor_password', true);
BEGIN
    IF pw IS NULL OR pw = '' THEN
        RAISE EXCEPTION 'transferops.auditor_password is not set; the loader must '
                        'supply it from TRANSFEROPS_AUDITOR_PASSWORD';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'transferops_auditor') THEN
        EXECUTE format('CREATE ROLE transferops_auditor LOGIN PASSWORD %L', pw);
    ELSE
        EXECUTE format('ALTER ROLE transferops_auditor LOGIN PASSWORD %L', pw);
    END IF;
END
$$;

DO $$
BEGIN
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        ALTER ROLE transferops_auditor NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA tr_gov TO transferops_auditor, transferops_reader;
GRANT INSERT, SELECT ON tr_gov.agent_audit TO transferops_auditor;
GRANT USAGE, SELECT ON SEQUENCE tr_gov.agent_audit_call_id_seq TO transferops_auditor;

-- The reader serves these to the observability endpoints, read-only.
GRANT SELECT ON tr_gov.etl_run, tr_gov.agent_audit TO transferops_reader;
