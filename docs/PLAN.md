# Transfer & Conversion Intelligence Platform — Complete Project Plan

A runnable, open-stack replica of Infineon's transfer-project performance reporting
platform, built to the DORA-inspired modernisation spec. This plan carries the
project from its current state through to the interview-ready package you can walk
in with.

The plan serves two audiences at once:
- **The engineering build** — an actual working system you can run and screen-share.
- **The interview proposal** — every phase embodies a point the architecture doc
  says you should make to the business owner, so the repo *is* the proposal,
  made concrete.

> **Recovered file.** The original `docs/` contents were lost from disk; this was
> rebuilt from the copy in the working session and updated to the current state.
> The two source PDFs were not recoverable and need re-adding from their origin —
> the one item on this page that code cannot close. The loss is also why the
> repository is now under version control and pushed to a remote.

---

## 0. Current status

> **Numbering note.** This file and `README.md` previously numbered the phases
> differently, so "Phase 3" meant two different things depending on which document
> you read. Both now use the single sequence in §3.

| | |
| --- | --- |
| **Done** | **Phases 1–12.** Data foundation, governed metric layer with a catalogue-vs-implementation gate, read-only analytics API, two-audience dashboards, self-explaining assistant, entitlement enforcement in row-level security, observability with a persisted audit trail, layered RAW→STAGING→CORE ingestion with three DQ tiers **on both engines**, the `v0-legacy` before/after contrast, the interview package, an Airflow DAG, CI, a fenced AI layer (`ai/`, `tr_ai`, `/ai/*`), a twelve-screen React product console, and a branded Keycloak self-service identity flow with email verification and recovery. T-017 reconciles exactly (118 / +25 / +28 / on-time No). **207 assertions across eighteen suites**, green on DuckDB and PostgreSQL. Under version control. |
| **Next recommended** | Nothing outstanding. Every item in every source plan is now built, including the three previously scoped out as non-goals (Qdrant/RAG, LoRA fine-tuning, Kubernetes). Under version control and pushed to `origin`. The only remaining item is external and cannot be rebuilt from code: re-adding the two lost source PDFs. |
| **Target end-state** | Two-audience BI, a product console, and a self-explaining read-only agent over one governed metric foundation, with RBAC, observability, an optional model layer that cannot compute, and a one-page proposal + demo script for the business owner. |

### What the original sequencing got wrong, in hindsight

The first plan put BI or the agent immediately after the data foundation.
Building the **API** first turned out to matter more than either: the dashboards
and the assistant now consume the same governed contract, so neither can drift
into holding its own opinion about a metric, and the provenance envelope that
makes the assistant explainable already existed when the assistant was written.

Three defects also surfaced inside the "finished" Phase 1 — a registered metric
with no implementation, and two views returning populations their own definitions
excluded. That is the whole argument for `tests/governance_checks.py`, and it is
why the catalogue-vs-implementation gate now belongs to the foundation rather
than being a nicety. Two of the three were found by reading; the third was found
by the gate itself, on its first run.

---

## 1. Guiding principles (non-negotiables, straight from the spec)

1. **Evolutionary, not rip-and-replace.** Old path stays alive; migrate one flow at a time.
2. **Preserve history explicitly.** Immutable baseline + schedule revisions + snapshots. Never overwrite the past.
3. **One governed definition per metric.** Registered in a catalogue with owner, grain, population, version — and *tested* against the implementation.
4. **Reconcile before you trust.** No legacy metric retires until golden projects match.
5. **The agent queries the metric catalogue, never raw SQL.** LLM is untrusted; the policy engine and query executor are trusted.
6. **Security below the visualisation layer.** A dashboard filter is not a boundary. Enforcement sits in the database.
7. **Two tracks always run in parallel.** RUN (urgent reports/fixes) + CHANGE (renovation). Capacity ~50/50 early, shifting toward CHANGE.

---

## 2. Target architecture at a glance

```
Sources → RAW → STAGING → CORE (+ revisions + snapshots) → METRIC → MART → API → BI / AI
                                    ▲                                        │
                             GOVERNANCE (metric dictionary · RBAC · lineage · audit)
```

Schemas: `tr_raw · tr_stg · tr_core · tr_metric · tr_mart · tr_gov`.

Everything above the metric layer reaches data through the read-only API, and
everything reaches project rows through `tr_core.dim_project`, which is where the
row-level policy lives.

---

## 3. Build phases

| Phase | Outcome | Portfolio-critical? | Status |
| --- | --- | --- | --- |
| 1 | Data foundation, metric core, governance, golden + governance gates | must-have | **done** |
| 2 | Read-only analytics API with provenance envelopes | must-have | **done** |
| 3 | Dashboards — two audiences, API-only, self-describing panels | must-have | **done** |
| 4 | Self-explaining read-only assistant + eval set | differentiator | **done** |
| 5 | RBAC: roles vs entitlements, row-level security, Keycloak realm | must-have | **done** |
| 6 | Observability: Prometheus/Grafana, persisted audit, adoption metrics | depth | **done** |
| 7 | Full RAW→STAGING→CORE ingestion + layered data-quality framework | depth | **done** |
| 8 | `v0-legacy` before/after contrast + 20–50 golden cases | high demo value | **done** |
| 9 | Polish + interview package (one-pager, diagrams, pilot, demo script) | must-have | **done** |
| 10 | Portable staging (both engines), Airflow DAG, GitHub Actions CI | depth | **done** |
| 11 | Semantic knowledge base, fine-tuning experiment, containers + Kubernetes | breadth | **done** |
| 12 | Fenced AI layer (`tr_ai`, `/ai/*`) + the React product console | product | **done** |

**On the three that were once non-goals.** Qdrant/RAG, LoRA fine-tuning and
Kubernetes were originally scoped out on the principle of introducing a tool only
for clear value, then built on request. Building them did not weaken that
principle — it sharpened where each one belongs:

- **Retrieval** is advisory and cannot change a decision. It widens what the
  assistant can *explain*, never what it can *assert*.
- **Fine-tuning** is an experiment the platform does not load, guarded by a test
  asserting `agent/` imports no model. Its dataset is generated from the
  catalogue, because weights are the one artefact that cannot be diffed.
- **Kubernetes** deploys the stateless services only. The warehouse stays in
  Compose.

Each is built *and* bounded. That is a better interview answer than either
"I skipped it" or "I built it because the plan said so."

*(Effort is in "focused half-days" — one working-student evening.)*

---

### Phase 1 — Data foundation & metric core — DONE

**Goal.** A clean six-layer warehouse with real schedule history and one governed
definition per KPI, proven correct.

**Shipped.** `sql/00_schemas.sql` … `04_marts.sql`; `etl/generate_data.py`
(260 projects, 904 revisions, 3,694 snapshots); `etl/run.py`;
`tests/golden_projects.py`; `tests/governance_checks.py`.

**Acceptance (met).** Golden T-017 reconciles exactly; all core-layer DQ gates
pass; runs identically on DuckDB and PostgreSQL; every registered metric has an
implementation and no metric returns an excluded population.

---

### Phase 2 — Read-only analytics API — DONE

**Goal.** One governed contract that both BI and the assistant consume, so neither
can develop its own opinion about a metric.

**Shipped.** `api/db.py` (read-only session, parameterised access, scope carrier),
`api/catalogue.py` (provenance envelope), `api/main.py` (the metric, mart,
project, catalogue and service routes), `tests/api_checks.py`. The mart routes and
`api/ai_routes.py` were added later, in Phase 12, against the same contract.

**Acceptance (met).** The API computes nothing — it selects from `tr_metric` /
`tr_mart` only; every metric response carries definition, population, version,
filters and data vintage; the session physically cannot write; T-017 through the
API equals T-017 in the golden test. The catalogue publishes *where* each metric
is served, so routing cannot drift from governance.

---

### Phase 3 — Dashboards, two audiences — DONE

**Shipped.** `bi/client.py`, `bi/server.py`, `bi/static/` (page, design
tokens, hand-built SVG charts), `tests/bi_checks.py`.

Management view: health tiles, throughput, forecast reliability in plain language.
Technical/PMO view: box plots, drift, horizon curve, stage bottlenecks, and a
per-project drill-down plotting every preserved replan against the frozen baseline.

**Acceptance (met).** Every panel sources from the API; the `bi/` package contains
no connection string and no SQL, asserted by test; every panel renders the
definition and filters that produced it.

---

### Phase 4 — Self-explaining assistant — DONE

**Shipped.** `agent/schema.py`, `resolver.py`, `executor.py`, `explain.py`,
`app.py`, `agent/evals/`, `tests/agent_checks.py`.

Answers with **no LLM**: resolution, filters, permissions and arithmetic are
deterministic, therefore testable. A model can be added for phrasing later and
would still have to emit a `MetricQuery` bounded by the same catalogue.

**Acceptance (met).** 26/26 eval cases. Metric resolution, filter resolution,
abstention precision and provenance completeness all 100%; security violations 0.
Ambiguous questions ("which projects are late?") offer the three registered
candidates rather than guessing. Injection attempts and action requests refuse.

---

### Phase 5 — RBAC and entitlements — DONE

**Shipped.** `sql/09_entitlements.sql` (portable model), `sql/10_rls.sql`
(enforcement + least-privilege reader role), `api/auth.py`,
`keycloak/realm-export.json`, `tests/rbac_checks.py`.

**Acceptance (met).** 10/10. `manager.auto` sees 75 projects, `manager.power` 89,
admin 260. Filtering for an unentitled portfolio returns nothing; a cross-portfolio
project lookup 404s; an unknown user is rejected rather than defaulted; the
assistant inherits the caller's scope and cannot be talked into widening it; an
unset scope discloses zero rows.

**The three-part trap worth remembering:** `FORCE ROW LEVEL SECURITY`, a
non-superuser connection, and `security_invoker` on every view. Miss any one and
the policy is installed but inert — the first run of these tests had all ten
checks "passing" the wrong way for exactly that reason.

---

### Phase 6 — Observability — DONE

**Shipped.** `observability/telemetry.py` (shared Prometheus registry),
`prometheus.yml`, `grafana/` (datasource + 13-panel dashboard, provisioned as
code), `sql/11_observability.sql` (`tr_gov.etl_run`, `tr_gov.agent_audit`, the
least-privilege `transferops_auditor` role), `agent/audit.py`,
`tests/observability_checks.py`.

**Acceptance (met).** 11/11. Prometheus scrapes both services; pipeline gauges
read warehouse state rather than process state; API latency is labelled by route
template so cardinality stays bounded; an abstention is counted as an abstention
and an injection attempt as a security event; audit rows persist under a role that
gets `permission denied for schema tr_core`; a dead audit database degrades the
trail without failing the answer.

**Two decisions worth keeping.** Telemetry is served from
`/observability/metrics`, because `/metrics/*` already means governed KPIs here
and reusing the prefix would be the exact naming collision the catalogue exists to
prevent. And `etl_run` / `agent_audit` use `CREATE TABLE IF NOT EXISTS` while
everything else is dropped and rebuilt — an audit trail wiped by a warehouse
reload is not an audit trail.

**Interview value.** Closes the "monitoring for GenAI tool adoption" loop, and
`task success` is the metric that speaks directly to the self-explaining goal:
can a user who does not know the hidden filter logic still get the right answer?

---

### Phase 7 — Ingestion & data-quality framework — DONE

**Shipped.** `sql/05_raw_tables.sql` (untyped landing + quarantine),
`sql/06_staging.sql` (typing, standardisation, dedup), `etl/ingest.py`,
`etl/dq_checks.py` (three tiers, 19 checks), `tests/ingestion_checks.py`.

**Acceptance (met).** 8/8. A corrupted batch is caught at the ingestion tier by
the right check; 3 REJECT rows are held back while the clean 260 still land; RAW
still holds `2026-13-45` byte for byte; re-delivery doubles RAW and leaves
STAGING at 260; the same layered path runs on PostgreSQL; the layered path and
the bulk loader produce identical CORE.

**The decision worth keeping: severity.** `REJECT` rows have no safe
interpretation and never reach CORE. `WARN` rows are a delivery problem staging
already resolves — a duplicate redelivery collapses deterministically, and
dropping that project would lose good data over something the pipeline handled.
Treating every finding as fatal is how teams end up disabling their own gates.

**Portability decision.** `06_staging.sql` stays byte-identical across DuckDB and
PostgreSQL. Engine-specific safe-cast behavior lives in
`06_functions_duckdb.sql` and `06_functions_postgres.sql`, so the ingestion logic
does not fork while malformed source values are still quarantined consistently.

---

### Phase 8 — The `v0-legacy` contrast + golden portfolio — DONE

**Shipped.** `legacy/v0_legacy.sql`, `tests/legacy_reconciliation.py`, and a
golden set grown from 1 project to **31 across 11 categories** (38 assertions).

**Acceptance (met).** 10/10. All four headline metrics reconcile between v0 and
v1 across the whole portfolio — the legacy SQL is *correct*, which is precisely
why the pattern survives for years. The failure is governance, not arithmetic: a
second legacy view scores on-time against the latest replan rather than the
frozen baseline, reading **44.0%** where the baseline says **41.5%**.

**The methodological point.** Golden expectations are now recomputed in Python
from the source CSVs rather than by querying the views under test. Two
independent implementations have to agree. The previous version asserted the
system's own output back at it, which would have passed forever.

Cancelled projects assert *absence* from every metric view — the direct
regression test for the population defect that shipped in Phase 1's "done".

---

### Phase 9 — Polish & interview package — DONE

**Shipped.** `docs/PROPOSAL.md` (one page), `docs/ARCHITECTURE.md` (a business
diagram, an engineering diagram, and the assistant's trust boundary),
`docs/DEMO_RUNBOOK.md` (5 minutes, minute by minute, with expected output and
the questions to expect), `docs/PILOT.md` (three weeks plus the spoken "how would
you start" answer).

**Verified, not written from memory.** Every command in the runbook was executed
against the running stack: the RBAC switch returns 75 / 89 / 260, and the three
assistant questions return `rank` / `clarify` / `refuse` exactly as scripted.

**The ordering decision worth keeping.** The runbook leads with reconciliation,
not with the assistant. Trust first — once the numbers are shown to reconcile,
everything after it is credible. Lead with the AI and it is just another chatbot
demo.

*Original scope, for reference:*

README with the before/after story and screenshots; the one-page modernisation
proposal; two diagrams (simplified for the business audience, full six-layer); the three-week
pilot narrative; a 5-minute demo runbook: generate → reconcile → box plots → ask
the assistant two questions → switch user and show the answer change → audit trail.

**Effort.** 4–6 half-days.

---

### Phase 12 — The AI layer and the product console — DONE

Two additions that sit *above* everything already built, and neither was allowed
to change anything below it.

**Shipped — the AI layer.** `ai/gateway.py` (one provider-agnostic client:
Anthropic SDK, or any OpenAI-compatible endpoint including local models),
`snapshot.py`, `insights.py`, `risk.py`, `ask.py`, `email.py`, `store.py`,
`refresh.py`, `prompts.py`; `api/ai_routes.py` (seven routes); `sql/12_ai.sql`
(`tr_ai` and the write-only `transferops_ai` role); a `refresh_ai_caches` task on
the DAG; `tests/ai_checks.py`.

**Shipped — the console.** `web/` — React, TypeScript, TanStack Router and Query,
twelve screens, four of them admin-only; a typed API client; the Vite dev server
proxies `/api` and `/assistant` so the browser holds no credential of its own;
`tests/web_checks.py`; a typecheck-and-build step in CI.

**Acceptance (met).** 12/12 on the AI fence and 7/7 on the console, both suites
running with no model, no warehouse and no Node toolchain — they read source
rather than executing it, which is why CI can prove the platform degrades instead
of proving a provider was reachable that morning.

**The four decisions worth keeping.**

- **The model may phrase a number, never produce one.** Every prompt is grounded
  in a snapshot fetched from the governed API under the caller's identity. There
  is no database handle in `ai/`, so a narrative cannot name a portfolio its
  reader may not see — because it was written from numbers that excluded it.
- **A risk score is not a metric.** It is the one number that comes out of a
  model, so it lives in `tr_ai.project_risk` and a test asserts no risk field
  ever appears in `tr_gov.metric_definition`. A model's opinion that quietly
  acquires a metric code is how "the system says this project is at risk" stops
  being traceable to anything.
- **Cached output expires on time *or* on vintage.** The 24-hour TTL bounds
  staleness; the stored `data_as_of` invalidates a briefing the moment a new load
  lands. A briefing about last week's warehouse beside this week's chart is worse
  than no briefing.
- **The console needs a much louder gate than `bi/` did.** `bi/` earns "holds no
  SQL, no credentials, no metric logic" by having almost nothing in it. The
  console is a large surface, so the same claim is asserted explicitly — right
  down to no colour literal outside the token stylesheet and no hard-coded health
  threshold. The first quick fix that computes a percentile in a component would
  put the platform back to two definitions of cycle time.

**What this phase deliberately did not do.** It did not put the console in the
container image (static assets belong behind the ingress, not inside a Python
service), it did not make the AI layer required (no key configured is the
default, and the state CI runs in), and it did not let a model outage fail a
warehouse refresh.

---

## 4. Cross-cutting workstreams

- **Testing.** Golden reconciliation (numbers) + governance reconciliation
  (definitions) + mart reconciliation (the console's rollups) + DQ tiers
  (pipeline) + agent evals and the AI fence (models) + console isolation
  (frontend) + entitlement checks (security). Every transformation change re-runs
  all of them.
- **Docs.** Each metric enters `tr_gov.metric_definition` *before* it is used
  anywhere, and the governance gate fails the build if it is registered without an
  implementation.
- **Git hygiene.** Under version control and pushed to a remote. The `docs/` loss
  that required this file to be rebuilt is the argument for it, and the reason
  line endings are pinned in `.gitattributes` rather than left to whoever clones.

---

## 5. The 24-month operating model

```
TRACK A — RUN    (urgent reports, bug fixes, new filters/calcs, user support)
TRACK B — CHANGE (data architecture, metric standardisation, migration, testing, AI)
early:  ~50–60% RUN / 40–50% CHANGE      later: ~30–40% RUN / 60–70% CHANGE
```

**Migration rule for every legacy component:** discover → document current result →
define canonical rule → rebuild calculation → validate vs golden → rebuild dashboard
→ dual-run → business acceptance → retire old. *Never delete before behaviour is
understood.*

---

## 6. Interview deliverables

1. The running repo — reconciliation, box plots, assistant, dashboards, and a live
   RBAC switch where two users get different answers to the same question.
2. The one-page proposal.
3. The simplified architecture diagram.
4. The three-week pilot plan.
5. The "how would you start" answer — delivered as *"here, let me show you."*

The framing line: *"I separate source data, business calculation, and presentation
so a metric like cycle time is defined once and reused everywhere — then the AI
sits on trusted metrics instead of raw tables."*

The strongest single demo is the forecast-accuracy-by-horizon curve
(2 → 6 → 11 → 30 days median error as the horizon lengthens): it is one endpoint,
it needs the snapshot history to exist at all, and it makes the case for measuring
forecasts at controlled horizons in about fifteen seconds.

---

## 7. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Scope creep (rebuild everything) | Ship the demo path first; depth phases are optional. |
| Framework churn | Pin versions; the assistant's query-object contract stays framework-agnostic. |
| Agent hallucination / injection | Deterministic resolver, read-only role, eval set, injection cases. |
| A model inventing or leaking a figure | Prompts grounded only in a snapshot fetched under the caller's identity; no database handle in `ai/`; closed tool list; filters merged, never replaced. |
| Model output mistaken for a governed metric | It lives in `tr_ai`, never `tr_metric`, and a test asserts nothing there is registered in the catalogue. |
| Provider outage or cost spike | Optional by default and degrades per surface; the refresh endpoint is HMAC-signed and refuses unless the secret is set; a failed refresh never gates the warehouse. |
| Metric logic creeping into the frontend | `tests/web_checks.py` — no SQL, no definitions, no thresholds, no colour literals outside the token file. |
| Metric drift | Everything through `tr_gov.metric_definition`; governance gate on every change. |
| Security theatre | RLS proven by tests that attack the boundary, not by asserting it exists. |
| Over-engineering | Introduce a tool only for clear value. |
| Work loss | Closed: under version control and pushed to a remote, after an earlier `docs/` loss made the case. |

---

## 8. Definition of done

- **Per phase:** acceptance criteria pass; new metrics are in the catalogue *and*
  implemented; golden + governance + DQ + eval + RBAC suites green; artifacts
  provisioned from code.
- **Overall:** clone → `make build && make test` → `make pg-up && make pg-build &&
  make test-pg` → working assistant + dashboards + adoption monitoring, reconciling
  to golden numbers, with a one-page proposal and a 5-minute demo runbook.
