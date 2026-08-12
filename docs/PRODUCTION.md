# Production readiness

This file is deliberately two lists: what the repository now enforces, and what
it cannot. The second list is the more useful one. A prototype that claims to be
production-ready is worse than one that says exactly where the line is, because
the line is where the next person gets hurt.

> **Honest framing.** A production platform of this shape is a
> [20–34 FTE-month programme](PROPOSAL.md). What follows is the hardening that
> belongs to the *code* — the part that can be done without knowing the target
> environment. Everything under "Still required" needs decisions and
> infrastructure that only the operating organisation can supply.

---

## Closed, and gated by a test

Every item here is asserted in [tests/security_checks.py](../tests/security_checks.py),
so it fails the build rather than drifting.

### Authentication was bypassable — fixed

`TRANSFEROPS_AUTH=enforce` accepted the `X-Demo-User` header. Sending one header
and no credentials returned a full `PLATFORM_ADMIN` identity with visibility of
the entire portfolio, in the mode the documentation called production.

The header is an *unauthenticated assertion of identity*. It is now honoured only
in demo mode, and refused with 401 otherwise.

### The default posture is now fail-safe

`TRANSFEROPS_AUTH` defaults to **`enforce`**. A deployment that forgets to
configure it lands in the safe state rather than the convenient one; demo mode
must be switched on deliberately, and every process logs a warning while it is.

The test suites opt into demo mode explicitly, which is why each one declares it
at the top — they drive `manager.auto` and `admin.demo` rather than standing up
an identity provider.

### Token validation actually validates

Audience verification was disabled (`verify_aud: False`), which accepts a token
minted for any *other* client in the same realm — one compromised low-privilege
application becomes access to this one. Signature, issuer, audience and expiry
are now all checked, and the published keys are cached on a TTL so realm key
rotation is survivable rather than an outage.

### Credentials are supplied, not committed

`CREATE ROLE transferops_reader LOGIN PASSWORD 'reader'` lived in
`sql/10_rls.sql`. A credential in version control is a credential published with
the repository, and rotating it meant a code change.

The SQL now reads its passwords from a session setting, and
[etl/credentials.py](../etl/credentials.py) decides what that setting holds:

| Loading | Behaviour with no password set |
| --- | --- |
| localhost / container host | documented dev value, with a warning on every run |
| any other host | **hard failure** — refuses to install a default credential |

Set `TRANSFEROPS_READER_PASSWORD` and `TRANSFEROPS_AUDITOR_PASSWORD` per
environment. Re-running the loader re-applies them, so rotation is a redeploy.

### Builds are reproducible

Dependencies are pinned exactly. A `>=` floor means the image built today and the
one built next month are different software, so a green pipeline stops being
evidence about the artefact you are deploying.

A `.dockerignore` now bounds the build context. The Dockerfile copies named
directories, but the *context* is sent whole — so a stray `.env` or a local
warehouse was handed to the builder regardless. The image is two-stage, so the
compiler toolchain some wheels need does not ship to production.

### Operational visibility

- **Structured logs.** One JSON object per line, with a request id honoured from
  an inbound `X-Request-ID` and echoed back, so a trace survives across services.
  Identity and route template are logged; result rows and portfolio contents are
  not — a log that becomes a second copy of the governed data is a liability.
- **Alerting rules** in [observability/alerts.yml](../observability/alerts.yml),
  provisioned from version control. Each one had to answer "if this fires at
  03:00, is there something to do?" — stale data, no successful load, failing DQ
  gates, error rate, P95 latency, refused injection attempts, and answers going
  out without provenance.

### The AI layer is fenced, not trusted

Added late, and deliberately built so that nothing below it had to be re-reviewed.
[tests/ai_checks.py](../tests/ai_checks.py) asserts the fence, and does it with no
model configured — so the gate tests the platform rather than a provider's uptime.

- **No database handle in `ai/`.** Every figure is fetched through the governed
  API under the caller's resolved identity, so the row-level policy filters it
  before it reaches a prompt. A narrative cannot describe a portfolio its reader
  is not entitled to.
- **The tool list is closed and filters merge.** Six tools, each naming one
  governed endpoint in source. A model cannot name a path, and the caller's scope
  is applied *on top of* whatever it asked for, so a question cannot widen a view.
- **Model output is not a metric.** It lives in `tr_ai`, written by
  `transferops_ai` — INSERT/UPDATE on three tables and no SELECT anywhere in
  `tr_core`, `tr_metric` or `tr_mart`. Same argument as the auditor role, applied
  to the generator: a compromised AI layer writes a bad narrative and still
  cannot read a project row.
- **The endpoint that spends money is signed.** `POST /ai/refresh` verifies an
  HMAC against `TRANSFEROPS_AI_CRON_SECRET`, and refuses every request when the
  secret is unset rather than defaulting to open.
- **Failure is typed and per-scope.** `AiUnavailable` / `AiRateLimited` /
  `AiError` degrade differently, and one failing scope in the nightly refresh
  leaves the others warmed and lands in `tr_ai.run_log` with its error.

### The console holds nothing it could leak

The browser talks only to its own origin — Vite proxies `/api` and `/assistant`
in development, an ingress rule serves the same paths in a deployment — so the
console carries no credential and no service URL of its own.
[tests/web_checks.py](../tests/web_checks.py) asserts statically that `web/src`
contains no SQL, no DSN or driver, no registered metric definition, no hard-coded
health threshold, and no colour outside the token stylesheet. The admin-only
screens are hidden by a client guard, which is convenience: the API resolves
entitlements and the database enforces them, so the nav is never the boundary.

### Performance

- **Connection pooling.** The API opened a fresh connection and re-authenticated
  for *every query*; a single dashboard load cost seven. Pooled now, with the
  caller's scope re-applied on every checkout so a recycled connection can never
  carry the previous request's entitlements.
- **The N+1 in the envelope.** Every metric response re-queried the catalogue
  once per metric plus the data vintage. Both are now cached on short TTLs;
  `/metrics/portfolio` went from roughly 300 ms to **22 ms**.
- **Access paths.** The three fact tables had no indexes at all, so every join in
  the metric layer resolved by sequential scan. [sql/07_indexes.sql](../sql/07_indexes.sql)
  adds them, including a partial index for the frozen baseline and a covering
  order for the latest-revision window — and one on `dim_project.portfolio`,
  which the row-level policy filters on for every single read.

---

## Still required — and why the repo cannot close it

### Secret management

The DSNs still carry passwords as environment variables, and
`kubernetes/transferops.yaml` holds a `Secret` with literal values for the local
demo. Production needs those bound from an external store (Vault, Secrets
Manager, Azure Key Vault, or Sealed Secrets), which is a deployment decision this
repository cannot make. **What to do:** replace the `Secret` with an
`ExternalSecret`/`SecretProviderClass` and rotate the role passwords on a
schedule; the loader already re-applies them.

### The `X-Demo-User` header should not exist in production

It is correct as built — refused unless demo mode is on — but the safest
production posture is a build that cannot honour it at all. **What to do:** if
your threat model warrants it, drop the branch entirely and let Keycloak be the
only door.

### Schema migrations

`sql/01_core_tables.sql` drops and recreates. That is right for a reproducible
demo warehouse and wrong for a database holding history you cannot regenerate.
**What to do:** move to versioned migrations (Alembic, Flyway, Sqitch) before any
data exists that is not reproducible from source. The audit and ETL-run tables
already model the distinction — they are the only two created `IF NOT EXISTS`.

### Backup, restore and retention

Not addressed at all. `tr_gov.agent_audit` and `tr_gov.etl_run` are the tables
whose loss actually matters, since everything else rebuilds from source.
**What to do:** PITR on the warehouse, a tested *restore* (an untested backup is
a hypothesis), and a retention policy for the audit trail.

### Availability and scale

The API and dashboard are stateless and already run two replicas; PostgreSQL is a
single container with no replication, and no load test has been run.
**What to do:** a managed database with a replica and automated failover, and a
load test that establishes where the metric layer needs materialised views —
`/metrics/cycle-time` is the endpoint to watch, since it aggregates percentiles
across a chain of views and is the slowest by a wide margin.

### Rate limiting and quotas

Nothing bounds request volume per caller. The statement timeout and row cap bound
one *query*, not a client in a loop. **What to do:** enforce at the ingress or
gateway, where it belongs, rather than in application code.

### Supply chain

Dependencies are pinned but not hash-verified, and there is no vulnerability
scanning in CI. **What to do:** `pip install --require-hashes` against a compiled
lockfile, plus `pip-audit` and an image scan as pipeline gates.

### Sending governed data to a model provider

The fence controls *what* the model sees — entitlement-scoped, provenance-stamped
figures and nothing else. It cannot control what happens to those figures once
they leave the network. Portfolio names, site names and project identifiers are
in every prompt by design, because a briefing without them is useless.
**What to do:** decide this before enabling AI in an environment with real data —
a zero-retention provider agreement, a self-hosted or in-VPC model behind the
OpenAI-compatible adapter (which is why that adapter exists), or AI left off.
`TRANSFEROPS_AI_API_KEY` unset is a supported production configuration, not a
degraded one.

### Model cost, quotas and retention of generated output

Spend is bounded only by the cache TTL and the refresh schedule. There is no
per-tenant budget, no monthly ceiling, and no alert on spend. `tr_ai.insight` and
`tr_ai.project_risk` also accumulate: they are derived rather than historical, so
they are safe to prune, but nothing prunes them. **What to do:** a provider-side
budget alert, a quota at the gateway for the interactive `/ai/ask` path, and a
retention job on `tr_ai` — keep `run_log`, expire the rest with its vintage.

### Nobody reviews what the model wrote

Generated narratives are stamped, scoped and expiring, and a reader can check any
claim against the register beside it. What does not exist is a record of whether
anyone *did* — no thumbs-up, no flagging, no sampled human review. **What to do:**
if generated text is going to reach a steering committee, add feedback capture and
sample it, in the same spirit as the golden set: the assistant's evals score
resolution, and nothing yet scores narrative quality.

### Compliance and data handling

The data here is synthetic and the demo accounts are fictional. Real transfer-project
data brings retention rules, access review, and a lawful basis for processing —
none of which are engineering decisions.

---

## Pre-deployment checklist

```
[ ] TRANSFEROPS_AUTH is unset or 'enforce' (never 'demo')
[ ] TRANSFEROPS_READER_PASSWORD / TRANSFEROPS_AUDITOR_PASSWORD set from a secret store
[ ] TRANSFEROPS_API_DSN points at the least-privilege reader, not the schema owner
[ ] TRANSFEROPS_AI_DSN points at transferops_ai (write tr_ai, read nothing)
[ ] Keycloak realm reachable; KEYCLOAK_AUDIENCE matches the API's client id
[ ] Secrets bound from an external store, not the committed manifest
[ ] Migrations replace drop-and-recreate for any non-reproducible data
[ ] Backups configured AND a restore rehearsed
[ ] Alert rules loaded and routed to somebody who is actually on call
[ ] Rate limiting configured at the ingress

If AI is enabled — otherwise leave TRANSFEROPS_AI_API_KEY unset, which is a
supported configuration and not a degraded one:

[ ] Data-handling decision made and signed off: zero-retention terms, or an
    in-VPC model behind the OpenAI-compatible adapter
[ ] TRANSFEROPS_AI_CRON_SECRET set (unset means /ai/refresh refuses everything)
[ ] Provider budget alert configured; quota on /ai/ask at the gateway
[ ] Retention on tr_ai: keep run_log, expire insight and project_risk
[ ] The refresh runs AFTER the load, never concurrently

[ ] make test-all green against the target database
[ ] make web-build green, and web/dist served by the ingress (not the API)
```
