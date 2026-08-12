-- ============================================================================
-- Transfer & Conversion Intelligence Platform :: 09_entitlements.sql
-- Application ROLE and data ENTITLEMENT are deliberately separate concepts.
--
--   role        what kind of user are you?      viewer | analyst | manager | admin
--   entitlement which business data may you see? portfolio / site scope
--
-- A person can be a fully trusted analyst and still have no business seeing
-- another division's transfers. Collapsing the two into one "permission" is how
-- reporting platforms end up enforcing access by hiding dashboard filters, which
-- is not a security boundary at all.
--
-- Portable DDL: this file runs on both engines. The enforcement that binds it to
-- the data lives in 10_rls.sql, which is PostgreSQL-only.
-- ============================================================================

DROP TABLE IF EXISTS tr_gov.user_role;
DROP TABLE IF EXISTS tr_gov.data_entitlement;
DROP TABLE IF EXISTS tr_gov.app_role;
DROP TABLE IF EXISTS tr_gov.app_user;

CREATE TABLE tr_gov.app_user (
    username     VARCHAR PRIMARY KEY,
    display_name VARCHAR,
    email        VARCHAR
);

CREATE TABLE tr_gov.app_role (
    role_code   VARCHAR PRIMARY KEY,
    description VARCHAR,
    may_export  BOOLEAN,
    may_admin   BOOLEAN
);

CREATE TABLE tr_gov.user_role (
    username  VARCHAR NOT NULL,
    role_code VARCHAR NOT NULL
);

-- dimension_type/value keeps the model open: today portfolio and site, tomorrow
-- transfer type or product family, without a schema change per entitlement kind.
-- '*' means unrestricted on that dimension.
CREATE TABLE tr_gov.data_entitlement (
    username       VARCHAR NOT NULL,
    dimension_type VARCHAR NOT NULL,   -- PORTFOLIO | SITE
    dimension_value VARCHAR NOT NULL,  -- PF_AUTO | Dresden | *
    valid_from     DATE,
    valid_to       DATE
);

INSERT INTO tr_gov.app_role (role_code, description, may_export, may_admin) VALUES
('TRANSFER_VIEWER',  'Read-only dashboard access',                     FALSE, FALSE),
('TRANSFER_ANALYST', 'Portfolio analytics and assistant access',        TRUE,  FALSE),
('TRANSFER_MANAGER', 'Assigned portfolio only',                         TRUE,  FALSE),
('REPORT_DEVELOPER', 'Builds governed marts and dashboards',            TRUE,  FALSE),
('PLATFORM_ADMIN',   'Full access, including the metric catalogue',     TRUE,  TRUE);

-- Fictional demo accounts. Never real identities in a public repository.
INSERT INTO tr_gov.app_user (username, display_name, email) VALUES
('admin.demo',    'Avery Admin',    'admin.demo@example.invalid'),
('analyst.demo',  'Ana Analyst',    'analyst.demo@example.invalid'),
('manager.auto',  'Mo Manager',     'manager.auto@example.invalid'),
('manager.power', 'Pat Manager',    'manager.power@example.invalid'),
('viewer.demo',   'Vic Viewer',     'viewer.demo@example.invalid');

INSERT INTO tr_gov.user_role (username, role_code) VALUES
('admin.demo',    'PLATFORM_ADMIN'),
('analyst.demo',  'TRANSFER_ANALYST'),
('manager.auto',  'TRANSFER_MANAGER'),
('manager.power', 'TRANSFER_MANAGER'),
('viewer.demo',   'TRANSFER_VIEWER');

INSERT INTO tr_gov.data_entitlement
(username, dimension_type, dimension_value, valid_from, valid_to) VALUES
('admin.demo',    'PORTFOLIO', '*',        DATE '2020-01-01', NULL),
('analyst.demo',  'PORTFOLIO', '*',        DATE '2020-01-01', NULL),
('manager.auto',  'PORTFOLIO', 'PF_AUTO',  DATE '2020-01-01', NULL),
('manager.power', 'PORTFOLIO', 'PF_POWER', DATE '2020-01-01', NULL),
('viewer.demo',   'PORTFOLIO', 'PF_IOT',   DATE '2020-01-01', NULL);

-- ---------------------------------------------------------------------------
-- Local operator account.
--
-- Everything above this line is fictional. This block is not: it grants the
-- real Keycloak account that self-registered against the local realm, so the
-- owner of a fresh checkout is not locked out by the 403 that a verified-but-
-- unentitled user correctly receives.
--
-- Two consequences worth knowing before this repository goes anywhere public:
--   * the username is a personal email address, because the realm sets
--     registrationEmailAsUsername -- so it is a real identity in version
--     control, which is exactly what the comment above forbids;
--   * it is PLATFORM_ADMIN on every portfolio, which is the widest grant the
--     model can express.
-- Replace or delete this block before publishing, and prefer granting a
-- self-registered user from the operator runbook rather than from the seed.
-- ---------------------------------------------------------------------------
INSERT INTO tr_gov.app_user (username, display_name, email) VALUES
('parth.goswami838@gmail.com', 'Parth Nileshkumar Goswami', 'parth.goswami838@gmail.com');

INSERT INTO tr_gov.user_role (username, role_code) VALUES
('parth.goswami838@gmail.com', 'PLATFORM_ADMIN');

INSERT INTO tr_gov.data_entitlement
(username, dimension_type, dimension_value, valid_from, valid_to) VALUES
('parth.goswami838@gmail.com', 'PORTFOLIO', '*', DATE '2020-01-01', NULL);
