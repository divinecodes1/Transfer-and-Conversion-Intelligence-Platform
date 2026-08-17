# Transfer & Conversion Intelligence Platform

A runnable, open-stack replica of the transfer-portfolio reporting platform
a clean **six-layer architecture**
with governed metrics and a golden-project reconciliation gate.

Built to the modernisation spec: preserve schedule history explicitly, define each
KPI once as a governed product, and keep BI and the AI assistant on top of one
trusted metric foundation.

> **Status:** complete and runnable end to end — warehouse, governed metric layer,
> layered ingestion, analytics API, two-audience dashboards, a React product
> console, a fenced AI layer, a self-explaining assistant, entitlement
> enforcement, observability and the interview package.
> 207 automated assertions across eighteen suites.

---

## If you have five minutes

```powershell
.\scripts\demo.ps1          # or: make demo
```

One command. Database, warehouse, API, assistant and console, seeded and open
in a browser. `Ctrl+C` stops it.

Then, in order:

| | Screen | What it shows |
| --- | --- | --- |
| 1 | **Overview** | on-time rate, cycle time, and a briefing that cites its own figures |
| 2 | **Readiness** | in-flight work worst-first; qualification is the binding constraint |
| 3 | **T-002** | 77.15% ready, limited by qualification — the number is a weighted mean of seven dimensions whose weights live in a table |
| 4 | **Similar transfers** | what happened to comparable completed transfers, scored deterministically so the match can be argued with |
| 5 | **Identity menu** | switch `admin` → `manager.auto`; the same screen drops to one portfolio, enforced by row-level security in the database rather than by hiding a filter |

**The one claim worth testing:** every panel states the metric definition, the
population, the filters applied and the data vintage that produced its number —
and a test suite fails the build if the catalogue and the SQL ever disagree.

Three documents, in the order a reviewer wants them:
[Proposal](docs/PROPOSAL.md) (one page) ·
[Architecture](docs/ARCHITECTURE.md) (logical, physical, security and delivery views) ·
[Production readiness](docs/PRODUCTION.md) (what is hardened, and what is not)

<details>
<summary>Everything else</summary>

[Demo runbook](docs/DEMO_RUNBOOK.md) (minute by minute) ·
[Pilot plan](docs/PILOT.md) (three weeks) ·
[Build sequence](docs/PLAN.md) ·
[Master plan](docs/MASTER_PLAN.md) ·
[Infineon → replica mapping](docs/mapping.md) ·
[AWS deployment](docs/aws-deployment.md) ·
[AI providers](docs/openai-configuration.md) ·
[Cost controls](docs/cost-controls.md)

</details>

---

```
        warehouse ──▶ governed metric layer ──▶ analytics API ──┬──▶ console + dashboards
        (history)     (one definition/KPI)     (read-only)      ├──▶ assistant
                                    ▲                           └──▶ AI layer (optional)
                        metric catalogue ◀───────────────────────────────┘
                        entitlements enforced in row-level security
```

---

## Why it's built the way it is

The existing system grew incrementally "on top, on top, on top" — the classic accreted
reporting stack (`VIEW_FINAL_NEW_V2`, KPI logic scattered across workbooks). The
renovation replaces that with named layers:

```
Sources → RAW → STAGING → CORE (+history) → METRIC → MART → BI / AI
                                    ▲
                             GOVERNANCE (metric dictionary, RBAC, audit)
```

Three ideas do the heavy lifting:

1. **Preserve history explicitly.** `fact_schedule_revision` keeps an *immutable
   baseline* plus every replan, and `fact_project_snapshot` keeps the forecast as
   known on each date. Without these, "original vs latest schedule" and
   forecast-accuracy analytics are impossible — the past gets overwritten.
2. **One governed definition per metric.** Every KPI lives once in `tr_metric` and
   is registered in `tr_gov.metric_definition` with owner, grain, population and
   version. No dashboard recomputes a metric its own way.
3. **Reconcile before you trust.** `tests/golden_projects.py` asserts hand-agreed
   numbers on representative projects — the automated version of the migration rule
   *"never retire a legacy metric until the new one reproduces the old numbers."*
   `tests/governance_checks.py` closes the other half: it asserts the catalogue and
   the calculation layer agree, so a registered metric can't go unimplemented and a
   view can't quietly return a population its own definition excludes.

## Quickstart (no server needed)

```bash
pip install -r requirements.txt
python etl/generate_data.py        # synthesise the transfer portfolio
python etl/run.py --engine duckdb  # load + run data-quality gates
make test                          # 104 assertions, nine suites, no server needed
```

On Windows environments without `make`, run the commands listed under the matching
Makefile target directly.

## Quickstart (full stack)

```bash
cp .env.example .env              # enforced auth + local-only development values
make pg-up && make pg-build        # PostgreSQL warehouse + RLS
make sso-up                        # Keycloak + Mailpit verification inbox (:8025)
make api                           # :8000  analytics API   (Swagger at /docs)
make agent                         # :8100  assistant       (POST /ask)
make dash                          # :8501  reference dashboard (no build step)
make web-install && make web       # :5173  React product console
make obs-up                        # :9090 Prometheus, :3000 Grafana
make test && make test-pg          # all 207 assertions
```

Open `http://localhost:5173`. The branded Keycloak page provides sign-in,
account creation and forgotten-password recovery. New accounts receive a
verification message in the local Mailpit inbox at `http://localhost:8025`; the
message never leaves the machine. After verification, an administrator still
assigns the account's role and portfolio entitlement before governed data is
visible. In production, replace the `KEYCLOAK_SMTP_*` values with the approved
SMTP relay and use HTTPS redirect origins.

Expected tail of the test run:

```
  [PASS] T-017 actual_cycle_time_days     expected=118    actual=118
  [PASS] T-017 schedule_deviation_days    expected=25     actual=25
  [PASS] T-017 completion_variance_days   expected=28     actual=28
  [PASS] T-017 on_time                    expected=False  actual=False
  …
  31 golden projects across 11 categories
  38 passed, 0 failed
```

Every expectation other than T-017 is **recomputed independently in Python from
the source CSVs**, never by querying the views under test — so two implementations
of each business rule have to agree. A reconciliation gate that asks the system
what it thinks and then asserts it said that would pass forever.

The AI layer is optional and **off by default**: copy `.env.example` to `.env`
and set `TRANSFEROPS_AI_API_KEY` to switch it on. With no key the console hides
its AI panels and everything else — dashboards, API, deterministic assistant —
works unchanged. That is the state CI runs in. See [The AI layer](#the-ai-layer).

## AWS Student Deployment

A public demo on the current six-month AWS credit Free Plan. Check the account
plan before provisioning; usage consumes the promotional balance:

```bash
aws freetier get-account-plan-state --region us-east-1
```

```bash
export TRANSFEROPS_OPERATOR=you@university.edu
./scripts/deploy-aws-student.sh      # ECR bootstrap -> images -> app -> SSM seed
./scripts/setup-github-actions.sh    # CI, via OIDC, no access key
```

Windows PowerShell uses the equivalent native workflow:

```powershell
$env:TRANSFEROPS_OPERATOR = "you@university.edu"
.\scripts\deploy-aws-student.ps1
```

```text
CloudFront -> S3 (private)   HTTPS console
Lambda Function URLs (3)    API, assistant and nightly refresh
CloudFront -> EC2            HTTPS Keycloak, no domain required
EC2 t3.micro                 Keycloak + NAT for private Lambda egress
Private RDS db.t4g.micro     warehouse + Keycloak databases, no public ingress
EventBridge -> Lambda        nightly refresh, runs for seconds
SSM Parameter Store          secrets + constrained rollout/seed automation
IAM OIDC -> role             GitHub Actions, no stored credential
```

Two components run continuously. There is no NAT Gateway, ALB, custom domain,
ECS, or EKS; the one EC2 host provides NAT for private functions. Gross-cost
budgets exclude credits so promotional balance does not hide the burn rate.

**The API runs on Lambda without a single application change.** AWS Lambda Web
Adapter runs the same `uvicorn api.main:app` that runs locally, so
`tests/api_checks.py` still drives the deployed contract — no Mangum, no handler.

**Keycloak uses HTTPS without a domain.** A dedicated CloudFront distribution
terminates TLS with the AWS-owned certificate, and the origin security group
accepts only CloudFront's managed prefix list. SMTP relay settings enable
registration verification and password recovery mail.

**CI actually deploys.** Federated login on AWS is an IAM OIDC provider and a
role inside your own account — no directory administrator, which is exactly what
blocked the Azure attempt.

The AI layer defaults to `TRANSFEROPS_AI_PROVIDER=mock` — no key, no credits,
every AI surface working. Similarity and delay-risk never used a model at all.

Tear it all down with `./scripts/destroy-aws-student.sh` (or the PowerShell
equivalent), which also checks for
the unattached Elastic IPs and orphaned EBS volumes a `terraform destroy` leaves
billing.

| | |
| --- | --- |
| [aws/architecture.md](aws/architecture.md) | what is deployed and why each choice |
| [aws/cost-strategy.md](aws/cost-strategy.md) | what each component costs, and the arithmetic |
| [aws/security.md](aws/security.md) | what holds, and what deliberately does not |
| [aws/migration-to-enterprise.md](aws/migration-to-enterprise.md) | variable change vs real work |
| [docs/aws-deployment.md](docs/aws-deployment.md) | step by step, and troubleshooting |
| [docs/openai-configuration.md](docs/openai-configuration.md) | providers, mock mode, cost controls |
| [docs/cost-controls.md](docs/cost-controls.md) | operator guide to staying inside the free tier |

## Deploy to PostgreSQL

```bash
docker compose up -d
python etl/generate_data.py
python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops
```

The same `sql/*.sql` files run on both engines — date arithmetic is portable, so
moving to Oracle later is a dialect change, not a redesign.

## The analytics API

```bash
docker compose up -d && python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops
uvicorn api.main:app --reload        # Swagger at http://127.0.0.1:8000/docs
python tests/api_checks.py           # contract checks
```

| Endpoint | Returns |
| --- | --- |
| `GET /catalogue` | every governed metric definition — what the agent resolves against |
| `GET /metrics/cycle-time` | cycle-time percentiles, groupable by fiscal year / transfer type / site |
| `GET /metrics/schedule-drift` | original-vs-latest movement off the frozen baseline |
| `GET /metrics/forecast` | forecast error bucketed by horizon before completion |
| `GET /metrics/stage-cycle-time` | milestone-to-milestone durations (bottleneck detection) |
| `GET /metrics/portfolio` | management rollup: throughput, on-time rate, median cycle time |
| `GET /metrics/completion-variance` · `/metrics/forecast-cycle-time` | the remaining two registered schedule metrics |
| `GET /projects` · `/projects/{id}` | open portfolio with health band; per-project revision + snapshot history |
| `GET /mart/kpis` · `/trend` · `/distribution` · `/accuracy` · `/projects` | the console's panel rollups, pre-aggregated in `tr_mart` |
| `GET /mart/filter-options` | the governed filter vocabulary, so no client hard-codes a site list |
| `GET /pipeline/runs` | recent `tr_gov.etl_run` history — what the ingestion screen reads |
| `GET /whoami` | the caller's resolved role and entitlement scope |
| `POST /ai/*` · `GET /ai/status` · `/ai/risk` · `/ai/runs` | the AI surface — see [The AI layer](#the-ai-layer) |

Three properties, each asserted in `tests/api_checks.py`:

**The API never computes a metric.** It selects from `tr_metric` / `tr_mart` and
nothing else. Health bands come from `mart_project_status`, not from thresholds
re-declared in Python — a second set of thresholds in the service layer is exactly
how two dashboards start disagreeing.

**Every answer is self-describing.** Metric responses carry the registered
definition, population, exclusions, version, the filters applied and the data
vintage — so a number can be reproduced in the dashboard, and the agent has
nothing left to invent:

```json
{ "metrics": [ { "metric_code": "FORECAST_ERROR_DAYS", "version": "1.0",
                 "definition": "actual_finish - forecast_finish_as_of_snapshot",
                 "population": "Completed projects with historical snapshots" } ],
  "filters_applied": {}, "data_as_of": "2026-08-01", "n_projects": 1700,
  "series": [ { "horizon_bucket": "0-29", "median_abs_error": 2.0 },
              { "horizon_bucket": "90+",  "median_abs_error": 30.0 } ] }
```

**The session physically cannot write.** The connection is opened read-only, so a
write is refused by PostgreSQL rather than by convention. The agent inherits that
posture rather than having to be trusted with it.

## Dashboards — two audiences

`make dash`. The reference dashboard: a static page reached **only through the
API**, with no build step and no Node toolchain anywhere near it. The `bi/`
package contains no driver, no connection string and no SQL — static assets
included — and a test asserts that, so "BI visualises, it never recomputes" is
structural rather than a promise.

*Management* leads with one number — on-time completion — then health bands,
throughput and forecast reliability in plain language. *Technical / PMO* gets
cycle-time box plots, drift either side of the frozen baseline, the horizon
curve, stage bottlenecks, and a per-project drill-down that plots every
preserved replan against that baseline.

**No charting library and no app framework.** The charts are hand-built SVG and
the server is the FastAPI already in `requirements.txt`, so the dashboard adds
*zero* dependencies. Colour is not hand-picked either: one validated palette
lives in CSS custom properties and every mark reads a role token, so no panel
can hold a private palette — the argument the metric layer makes about KPI
definitions, applied to colour. Categorical slots clear the lightness band,
chroma floor, colour-vision separation and normal-vision floor in both light and
dark; horizon buckets use a single-hue ordinal ramp because they are ordered;
schedule drift uses a diverging scale because its sign is the point; and health
bands use a reserved status scale that never doubles as a series colour and
always ships with a labelled dot rather than colour alone.

The route list is closed on purpose. A transparent `/api/{path}` proxy would
make the browser an unreviewed second client of the warehouse, so
[bi/server.py](bi/server.py) names one route per panel and a test asserts an
arbitrary API path is *not* reachable through the dashboard.

Every panel prints the definition, population, filters and data vintage that
produced it, rendered from the envelope the API sent rather than from anything
written in the page — a test asserts no registered definition is baked into the
frontend. That footnote is the deliberate answer to *"he knows which filters to
set, future users won't."* The chart explains its own scope instead of relying on
tribal knowledge, and every chart carries a table view beside it so no value is
reachable only by hovering.

## The product console

`make web-install` once, then `make web` — a React/TypeScript console on :5173,
proxying `/api` and `/assistant` to the two Python services so the browser only
ever talks to its own origin and holds no credential of its own.

Authentication uses Keycloak's Authorization Code flow with PKCE. The adapter
initialises before the router, access tokens stay in memory, and every API call
refreshes the short-lived token before forwarding it as a bearer credential.
Credentials, registration, verification and recovery remain on the branded
Keycloak pages. The same theme covers every step, including dark mode. Self-
registration proves email ownership; it does not grant portfolio access.

Fourteen screens. Overview leads with the management numbers and an
evidence-backed briefing; Projects is a searchable register with explainable
delay-risk scores; project detail plots every preserved replan against the frozen
baseline, and carries the transfer's readiness breakdown and its closest completed
precedents; Readiness ranks in-flight work by weighted preparedness, worst first,
and names the dimension constraining the portfolio; Network re-grains the same
governed metrics onto each source→target lane and identifies the stage that costs
that lane the most time; Distribution and Forecast carry the box plots and the horizon curve;
Reports produces print and CSV output plus audience-aware email drafts; Ask is a
full-page workbench over the same catalogue-bound answers; Catalogue is
`tr_gov.metric_definition`, rendered. Four screens are admin-only — Ingestion,
Connections, Automation and Access — and the guard is cosmetic on purpose: the
API resolves entitlements and the row-level policy enforces them, so hiding a
nav item is convenience, never the boundary.

The console is a much larger surface than `bi/`, so the same "holds no SQL, no
credentials, no metric logic" claim needs a much more explicit gate — otherwise
the first quick fix that computes a percentile in a component puts the platform
back to two definitions of cycle time. [tests/web_checks.py](tests/web_checks.py)
asserts seven properties statically, with no warehouse, no model and no Node
toolchain required: no SQL under `web/src`; no driver, DSN or connection string;
no registered definition text baked into the frontend; no colour literal outside
the design-token stylesheet (70 values, all in one file); every screen's data
access through the typed API client; no hard-coded metric threshold, because the
health band and the hit rate are banded in SQL and only displayed here; and no
service URL other than the two proxies.

Operational boundaries are explicit rather than implied. CSV files can be
validated in the console, while loading and rollback still run through the ETL
quality gates. Connection screens report service state, while credentials and
sync jobs stay server-side. Access screens show effective roles and entitlements,
while grants remain owned by Keycloak and the governance tables.

The console is deliberately **not** in the container image: it is static assets
with no runtime of their own, so `make web-build` produces `web/dist` for the
ingress or CDN that already terminates TLS, rather than growing a Node build
stage inside a Python service.

## The AI layer

Optional, off by default, and fenced. Everything a model does lives in
[ai/](ai/) and obeys one rule: **the model may phrase a number, never produce
one.** Every prompt is grounded in a snapshot fetched from the governed API,
under the caller's identity, through the same endpoints the dashboards call —
there is no database handle in `ai/` at all, so the row-level policy filters the
numbers before they are ever serialised into a prompt. A narrative cannot mention
a portfolio the reader is not entitled to, because it was written from numbers
that excluded it.

| Module | Job |
| --- | --- |
| `gateway.py` | one provider-agnostic client — Anthropic SDK, or any OpenAI-compatible endpoint (hosted, vLLM, Ollama) |
| `snapshot.py` | the governed metric snapshot every prompt is grounded in |
| `insights.py` | portfolio briefing · report summary · anomaly watch |
| `risk.py` | per-project delay-risk scoring |
| `email.py` | audience-aware report drafts — a draft, with no mail transport in the dependency list |
| `ask.py` | tool-calling question answering over six governed endpoints |
| `store.py` · `refresh.py` | the `tr_ai` cache and the nightly warm-up |
| `prompts.py` | every instruction the platform gives a model, in one file |

Five decisions carry the safety argument, each asserted in
[tests/ai_checks.py](tests/ai_checks.py):

**The tool list is closed.** Six tools, each mapping to one governed endpoint
written in `ai/ask.py`. The model cannot name a path, and filters are *merged*
rather than replaced — the caller's scope is applied on top of whatever the model
asked for.

**Risk scores are not metrics.** Delay risk is the one place a number comes out
of a model, so it lives in `tr_ai.project_risk` and never in `tr_metric`; a test
asserts no risk field ever appears in `tr_gov.metric_definition`. Every row
carries the model that produced it, the warehouse vintage it was scored against,
and a rationale quoting a governed number.

**A narrative expires on time *or* on vintage.** Cached output is stored with the
`data_as_of` it was written from and served only while that vintage still stands.
A briefing about last week's warehouse shown beside this week's chart is worse
than no briefing.

**The writer is not the reader.** Cache writes go through `transferops_ai`, which
holds INSERT/UPDATE on three tables in `tr_ai` and nothing anywhere else — no
SELECT in `tr_core` or `tr_metric`. A fully compromised AI layer can write a bad
narrative; it still cannot read a project row. Same argument as the auditor role,
applied to the generator.

**The prompts don't restate the catalogue.** `METRIC_RULES` is generated from the
provenance envelope the API attached, which comes from `tr_gov.metric_definition`.
A prompt written in its own words would be one more place for a definition to
drift — the exact failure the catalogue exists to end, reappearing as a prompt.

Everything degrades. With no key configured, `/ai/status` says so, the other
endpoints answer 503 with a readable reason, the console hides its AI panels and
the deterministic assistant carries on untouched. Failure modes are *named* —
`AiUnavailable` (not switched on, never an alert), `AiRateLimited` (worth a
retry, not worth waking anyone) and `AiError` — because collapsing them into one
string is how a rate limit ends up looking like an outage on a status page.

`make ai-refresh` warms the caches for the scopes people actually open and
re-scores in-flight projects, so the first person at their desk gets a briefing
about *this* load. The DAG sequences it behind the quality gates: a narrative
generated against a half-loaded warehouse is not stale, it is wrong, and it would
carry the new vintage stamp while describing the old data. The signed
`POST /ai/refresh` endpoint refuses every request unless
`TRANSFEROPS_AI_CRON_SECRET` is set — it is the one endpoint that spends money,
and a cron trigger anyone can fire is a way to spend an AI budget from outside.

## The assistant

`make agent`, then `POST /ask {"question": "..."}`.

```
question → resolve (catalogue vocabulary) → MetricQuery (validated)
         → execute (read-only governed API) → explain (with provenance) → audit
```

**It answers with no LLM at all**, and that is the design rather than a
limitation. Metric resolution, filters, permissions and arithmetic are
deterministic, so they are testable and cannot hallucinate.

That is now the *floor* rather than the whole story. `ai/ask.py` adds a
tool-calling mode for the phrasing the resolver misses, and it changed nothing
below the language layer: the model picks which governed endpoint to call and
with what filters, never what a metric means, and never reaches a database. When
no model is configured — the default, and the state CI runs in — the assistant is
exactly the deterministic resolver described here. The two modes answer from the
same catalogue, which is why adding one did not require trusting it.

It resolves *"which transfer type has the highest cycle time?"* but refuses to
guess at *"which projects are late?"* — that maps to three registered metrics,
and choosing one silently is how a management meeting ends up arguing about whose
number is right. It offers the three and asks.

`make evals` scores what actually matters, currently **26/26**:

| | |
| --- | --- |
| metric resolution accuracy | 100% |
| filter resolution accuracy | 100% |
| abstention precision | 100% |
| provenance completeness | 100% |
| **security violations** | **0** (target, not a percentage to improve) |

Injection attempts and action requests are refused: text arriving from users or
from project records is data, never instruction, and the assistant is read-only —
it explains, it never approves a rebaseline.

## Access control

Application **role** and data **entitlement** are separate: a fully trusted
analyst may still have no business seeing another division's transfers.

Enforcement is a PostgreSQL row-level policy on `tr_core.dim_project`, which every
metric view reaches through — so one policy scopes the whole metric and mart
layer, and the same rule binds the dashboards, the API, the assistant and anyone
with a `psql` prompt. Three things have to hold together, and missing any one
leaves the policy installed but inert:

1. `FORCE ROW LEVEL SECURITY`, or the table owner bypasses its own policy.
2. A **non-superuser** connection — superusers bypass RLS unconditionally, so the
   API gets a least-privilege reader role rather than the bootstrap account.
3. `security_invoker` on every view, or a view owned by the schema owner
   evaluates the policy as *its owner* and quietly returns everything.

It is fail-closed: an unset scope selects zero rows, so a forgotten `SET` produces
an obviously empty result rather than a silent full-portfolio disclosure.

```
manager.auto  → 75 projects      manager.power → 89 projects      admin → 260
```

Identity comes from Keycloak (`make sso-up`, realm in `keycloak/`) or, for local
work, an `X-Demo-User` header. Both resolve to the same entitlements, so the
enforcement below never learns which door a caller used. Claiming authority in a
question buys nothing — `tests/rbac_checks.py` asks the assistant to widen its own
scope and asserts it cannot.

## Observability

`make obs-up` — Prometheus on :9090, Grafana on :3000 (admin/admin), dashboard
provisioned from [observability/grafana/](observability/grafana/) rather than
hand-edited in a running instance, which is the same rule the metric layer follows.

Telemetry is served from **`/observability/metrics`**, not `/metrics`. In this
platform that prefix already means governed business KPIs (`/metrics/cycle-time`),
and serving counters from the same namespace would be precisely the naming
collision the metric catalogue exists to prevent.

What it measures is chosen to answer whether the *platform* is working, not
whether the process is alive:

| | |
| --- | --- |
| **Pipeline** | data freshness, last successful load, load duration, failing DQ gates — read from `tr_gov.etl_run` at scrape time, so a second replica can't report stale figures |
| **API** | request rate and P95 latency per endpoint, labelled by route template (`/projects/{project_id}`, never `/projects/T-017` — per-project series would make this unusable within a week) |
| **Assistant** | questions by intent and outcome, metric resolution, abstention reasons, security events, provenance completeness, P95 answer latency |

The panel that matters most is **questions answered by the governed platform**.
An assistant nobody trusts enough to ask is a failure however good its latency
graph looks — and *task success* is the direct measure of the self-explaining
goal: can a user who doesn't know the hidden filter logic still get the right
answer?

`tr_gov.etl_run` and `tr_gov.agent_audit` are the only tables in `sql/` created
with `IF NOT EXISTS` rather than dropped and rebuilt. An audit trail wiped by a
warehouse reload is not an audit trail.

The audit writer connects as `transferops_auditor`, which holds INSERT on that one
table and nothing else — a test asserts it gets `permission denied for schema
tr_core`. So a fully compromised assistant still cannot read a project row or
alter a metric. If the audit database is unreachable the answer is still served
and the trail is flagged degraded, because losing observability shouldn't take the
service down — but it should be visible that it happened.

## Semantic knowledge base

`make test-rag`. Four Qdrant collections — metric definitions, dashboard
metadata, architecture docs, user guides. `make rag-up` starts the server, but
retrieval runs the same engine **in-process by default**, so tests and the demo
work with no container and no model download.

The design decision that matters: **metric documents are generated from
`tr_gov.metric_definition`, not written by hand.** A hand-written glossary is just
a fourth place for a definition to drift — the exact failure the catalogue ended,
reappearing as documentation. A test asserts every generated document restates
the catalogue verbatim, and that no curated document contains a metric value.

Retrieval is strictly **advisory**. It runs *after* resolution and cannot change
it: it can't rescue a refusal into an answer, promote a clarification into a
guess, or supply a number. It attaches documents that help a human understand a
reply; authority stays with the catalogue and the governed tools. Ask it the
capital of France and it returns nothing rather than the least-bad match — a
relevance floor, because returning something for a question the corpus knows
nothing about is how a retrieval layer starts inventing authority.

## Fine-tuning — an experiment, not a dependency

`make dataset`. 127 instruction pairs, **generated from the metric catalogue**:
117 definition pairs plus 10 behavioural ones teaching abstention, refusal to
invent numbers, read-only posture and cohort discipline.

Weights are the one artefact here that can't be diffed against `tr_gov`. Once a
definition is baked into a model there's no grep that finds it, so the guard sits
on the dataset: [tests/finetuning_checks.py](tests/finetuning_checks.py) fails the
build if a metric version changes and the dataset wasn't regenerated, and asserts
no training pair states a value.

[train.py](fine_tuning/train.py) is a LoRA script; `torch`, `transformers` and
`peft` are deliberately **not** in `requirements.txt`.
[evaluate.py](fine_tuning/evaluate.py) scores dataset consistency without a model,
and abstention *with* one — because tuning reliably improves fluency and usually
degrades abstention, and a model that answers "which projects are late?" with a
number is less safe than the deterministic resolver it would replace.

A test asserts `agent/` imports no model loader at all, so "the platform doesn't
depend on this" is structural rather than a claim.

## Containers and Kubernetes

`make image` — one image, three entrypoints. The API, assistant and dashboard
share a codebase and dependency set, so three Dockerfiles would be three places
to forget a dependency. Runs as an unprivileged user.

`make k8s-up` — kind cluster, image loaded, [manifests](kubernetes/transferops.yaml)
applied. Deployed: api (2 replicas), assistant, dashboard, qdrant. **Not**
deployed: PostgreSQL, Prometheus, Grafana, Keycloak — stateful components stay in
Compose, because running a warehouse in a local kind cluster adds PersistentVolume
failure modes to a ten-minute demo and proves nothing architecturally.

[tests/k8s_checks.py](tests/k8s_checks.py) asserts what unapplied YAML usually
gets wrong: every Deployment has probes, resource limits and a non-root security
context; every Service selector matches a Deployment that exists; and the
dashboard mounts **no database secret** — so the "BI reaches data only through the
API" claim holds in the deployment, not just in the code. A NetworkPolicy enforces
the same boundary at the network level.

## The metric model

| Metric | Definition | Grain |
| --- | --- | --- |
| Actual cycle time | `actual_finish - actual_start` | project |
| Forecast cycle time | `forecast_finish - actual_start` | project/snapshot |
| Baseline finish deviation | `latest_planned_finish - baseline_finish` | project |
| Completion variance | `actual_finish - baseline_finish` | completed project |
| Forecast error | `actual_finish - forecast_as_of_horizon` | completed / horizon |
| Throughput | completed projects per fiscal period | portfolio / period |
| On-time rate | completed by baseline / completed | portfolio / period |
| Stage cycle time | milestone(n+1) − milestone(n) | project / stage |
| Cycle-time distribution | P25 / P50 / P75 / P90 | segment / period |

Distributions (medians, P75/P90) sit alongside means because the existing box plots show
that the *spread* of cycle time matters, not just the average.

## What the data demonstrates

Two results worth knowing for the interview, both produced by the marts:

- **Cycle-time distribution by fiscal year** (`mart_cycle_time_distribution`) — the
  box-plot source, with the P90 tail visible per transfer type.
- **Forecast accuracy by horizon** (`v_forecast_error`) — median absolute error is
  ~30 days at 90+ days out but ~2 days inside 30 days. That is exactly why forecast
  quality must be measured at *controlled horizons*: an org can look "accurate"
  simply by updating its forecast right before completion. The snapshot history is
  what makes this measurable.

## Repository layout

```
transfer-and-conversion-intelligence-platform/
├── sql/
│   ├── 00_schemas.sql        # six-layer separation
│   ├── 01_core_tables.sql    # canonical model + schedule/snapshot HISTORY
│   ├── 02_governance.sql     # metric dictionary (governed, versioned)
│   ├── 03_metric_views.sql   # one definition per KPI (the calculation layer)
│   ├── 04_marts.sql          # curated marts for BI (two audiences)
│   ├── 05_raw_tables.sql     # landing layer, untyped, + quarantine
│   ├── 06_staging.sql        # typing, standardisation, dedup
│   ├── 07_indexes.sql        # access paths for the metric layer (PostgreSQL)
│   ├── 06_functions_*.sql    # safe-cast shims so 06_staging.sql never forks
│   ├── 09_entitlements.sql   # roles vs data entitlements (portable)
│   ├── 10_rls.sql            # row-level enforcement + reader role (PostgreSQL)
│   ├── 11_observability.sql  # etl_run + agent_audit, survive rebuilds
│   ├── 12_ai.sql             # tr_ai: cached narratives, risk scores, run log
│   └── 13_readiness_network.sql # readiness weighting · lane re-grain · similarity
├── etl/
│   ├── generate_data.py      # synthetic transfer portfolio + full history
│   ├── run.py                # bulk loader (duckdb | postgres) — deploys
│   ├── ingest.py             # layered RAW→STG→CORE loader — demonstrates
│   ├── credentials.py        # role passwords from the env, never from the SQL
│   └── dq_checks.py          # three DQ tiers, with severity
├── legacy/
│   └── v0_legacy.sql         # the "before": accreted, correct, ungovernable
├── api/
│   ├── db.py                 # read-only session, parameterised access only
│   ├── auth.py               # Keycloak / demo identity → entitlements
│   ├── catalogue.py          # metric dictionary + provenance envelope
│   ├── ai_routes.py          # /ai/*, in-process against the governed routes
│   └── main.py               # FastAPI: /metrics/*, /mart/*, /projects, /catalogue
├── ai/                       # the fenced model layer — optional at runtime
│   ├── gateway.py            # one provider-agnostic client (Anthropic | OpenAI-compatible)
│   ├── snapshot.py           # the governed grounding snapshot; no DB handle here
│   ├── insights.py           # briefing · report summary · anomaly watch
│   ├── risk.py               # delay-risk estimates — never registered as metrics
│   ├── ask.py                # tool-calling over six governed endpoints
│   ├── email.py              # audience-aware drafts, with no mail transport
│   ├── store.py              # the tr_ai cache, written by a write-only role
│   ├── refresh.py            # the nightly warm-up, sequenced after the gates
│   └── prompts.py            # every model instruction, in one file
├── bi/
│   ├── client.py             # the dashboards' only route to data
│   ├── server.py             # static page + a closed list of panel routes
│   └── static/               # index.html · app.css (design tokens)
│                             # charts.js (hand-built SVG) · app.js (two views)
├── web/                      # the React product console (built, not shipped in the image)
│   ├── src/routes/           # fourteen screens; four admin-only
│   ├── src/lib/              # typed API client · mart queries · AI client · app state
│   ├── src/components/       # shell · charts · panels · AI surfaces · ui primitives
│   └── src/styles.css        # the only file holding a colour value
├── agent/
│   ├── schema.py             # the validated MetricQuery contract
│   ├── resolver.py           # question → metric, deterministic, catalogue-bound
│   ├── executor.py           # trusted half: governed API calls only
│   ├── explain.py            # answer + definition + scope + vintage
│   ├── audit.py              # persisted trail via a least-privilege role
│   ├── app.py                # FastAPI: POST /ask, GET /audit
│   └── evals/                # question → expected resolution, with a scorer
├── observability/
│   ├── telemetry.py          # Prometheus registry shared by both services
│   ├── logs.py               # structured JSON logs + request correlation
│   ├── prometheus.yml        # scrape config
│   ├── alerts.yml            # alert rules, provisioned as code
│   └── grafana/              # datasource + dashboard, provisioned as code
├── keycloak/
│   ├── realm-export.json      # OIDC client + registration/reset/verification
│   └── themes/transferops/    # branded login and email themes
├── tests/
│   ├── golden_projects.py    # reconciliation gate (numbers)
│   ├── governance_checks.py  # reconciliation gate (definitions)
│   ├── api_checks.py         # API contract gate
│   ├── mart_checks.py        # the console's rollups agree with the metric layer
│   ├── readiness_checks.py   # readiness weighting · lane re-grain · similarity
│   ├── bi_checks.py          # BI holds no SQL, no credentials, no baked definitions
│   ├── web_checks.py         # the console holds none of it either
│   ├── ai_checks.py          # the AI fence — asserted without a model
│   ├── agent_checks.py       # agent evaluation in-process
│   ├── rbac_checks.py        # entitlement enforcement
│   └── security_checks.py    # auth posture, credentials, pinning, build context
├── docs/
│   ├── PROPOSAL.md           # the one-pager
│   ├── ARCHITECTURE.md       # seven views: logical, data model, AWS topology,
│   │                         # request path, entitlement, pipelines, delivery
│   ├── DEMO_RUNBOOK.md       # five minutes, minute by minute
│   ├── PILOT.md              # the three-week plan
│   ├── PRODUCTION.md         # what is hardened, and what still isn't
│   ├── PLAN.md               # the build sequence and its acceptance criteria
│   └── mapping.md            # Infineon → replica mapping
├── .env.example              # every credential and switch, in one readable file
├── docker-compose.yml        # PostgreSQL (pgvector) deployment target
├── Makefile
└── requirements.txt
```

## Roadmap

One sequence, shared with [docs/PLAN.md](docs/PLAN.md).

| # | Scope | Status |
| --- | --- | --- |
| 1 | Data foundation, metric layer, governance, golden + governance gates | **done** |
| 2 | Read-only analytics API over the governed views, provenance envelopes | **done** |
| 3 | Dashboards: management + technical/PMO, API-only, self-describing panels | **done** |
| 4 | Self-explaining assistant: catalogue-bound resolution, abstention, eval set | **done** |
| 5 | RBAC: roles vs entitlements, row-level enforcement, Keycloak realm | **done** |
| 6 | Observability: Prometheus/Grafana, persisted audit trail, adoption metrics | **done** |
| 7 | Full RAW→STAGING→CORE ingestion with per-layer DQ tiers | **done** |
| 8 | `v0-legacy` before/after contrast + 20–50 golden cases | **done** |
| 9 | Interview package: one-pager, diagrams, pilot plan, demo runbook | **done** |
| 10 | Portable staging on both engines, Airflow DAG, GitHub Actions CI | **done** |
| 11 | Semantic knowledge base, fine-tuning experiment, containers + Kubernetes | **done** |
| 12 | Fenced AI layer (`tr_ai`, `/ai/*`) and the React product console | **done** |
| 13 | Transfer readiness, network intelligence and historical similarity | **done** |

## Test suites

| Suite | Asserts | |
| --- | --- | --- |
| `golden_projects` | 31 projects, 11 categories, independently recomputed | 38 |
| `governance_checks` | catalogue ↔ calculation layer agree | 4 |
| `mart_checks` | the console's rollups agree with the metric layer | 9 |
| `readiness_checks` | readiness weighting, lane re-graining and similarity, each recomputed | 13 |
| `legacy_reconciliation` | v0-legacy reproduces v1's numbers, and contradicts itself | 10 |
| `ai_checks` | the AI fence — closed tool list, merged filters, no metric leak | 13 |
| `web_checks` | the console holds no SQL, credentials, definitions or thresholds | 7 |
| `orchestration_checks` | DAG parses, delegates, and gates the run | 5 |
| `k8s_checks` | manifests parse, probe, limit and lock down | 9 |
| `auth_checks` | registration, verification, recovery, PKCE and SMTP configuration | 10 |
| `ingestion_checks` | quarantine by tier, RAW fidelity, idempotence, PostgreSQL parity | 8 |
| `api_checks` | contract, provenance, read-only enforcement | 9 |
| `bi_checks` | BI holds no SQL or credentials; panels self-describe | 10 |
| `agent_checks` | resolution, abstention, injection, provenance | 26 |
| `rbac_checks` | entitlement enforcement at the database | 10 |
| `security_checks` | auth posture, credential handling, pinning, build context | 10 |
| `observability_checks` | telemetry, audit persistence, auditor least privilege | 11 |
| `rag_checks` | knowledge base builds from the catalogue and stays advisory | 10 |
| `finetuning_checks` | generated dataset is current, safe and non-runtime-critical | 9 |

`make test` runs the **nine** server-free suites (104 assertions); `make test-pg`
runs the **nine** that need PostgreSQL (103); `make test-all` runs everything.
**207 assertions in total**, and [CI](.github/workflows/ci.yml) runs the same
gates in the same order against a real PostgreSQL on every push, then typechecks
and builds the console and the container image.

The AI gates are written to run **without a model**, and CI deliberately supplies
no credential. What that proves is the property worth proving: the platform
degrades correctly. A suite that needed a provider to be reachable that morning
would be testing the provider.

## Orchestration

[dags/transferops_pipeline.py](dags/transferops_pipeline.py) models the scheduled
refresh: extract → layered ingest with its three DQ tiers → golden reconciliation
and metric governance → AI cache warm-up, with retries, `max_active_runs=1` and
`catchup=False`.

The last task is placed there for ordering, not convenience: a narrative written
while the warehouse is half-loaded would carry the new vintage stamp while
describing the old data. It runs after the gates and never gates them in return —
a model outage must not fail a warehouse refresh that already reconciled, so it
records the failure and the run continues green.

Airflow is **optional and deliberately not in `requirements.txt`** — the pipeline
does not need an orchestrator to be correct, and `etl/ingest.py` runs standalone.
What an orchestrator adds is operational: schedule, retries, and backfills when a
definition changes and history must be rebuilt. So the DAG models exactly that and
nothing else. Every task delegates to the same functions the CLI calls, and a test
asserts `dags/` contains no SQL and no connections — an orchestrator that grows
its own copy of the pipeline is how scheduling starts quietly disagreeing with the
thing it schedules.

The quality gates run *after* the load and raise rather than warn: a refresh that
silently changes a KPI is worse than one that failed.

## The before/after

`make test-legacy`. [legacy/v0_legacy.sql](legacy/v0_legacy.sql) reconstructs the
accreted pattern — inline KPI formulas, duplicated baseline/latest resolution,
magic filters, no population definition — and its headline numbers **reconcile
exactly** with the governed layer across all 260 projects.

That is the point. It is not a strawman; it works, which is why the pattern
survives for years. The cost shows up elsewhere: a second view bolted on later
scores on-time against the *latest replan* instead of the frozen baseline, so the
same portfolio reads **44.0%** on-time where the baseline says **41.5%**. Every
replan moves the goalposts it is measured against. Nobody intended to game
anything, and no term was ever written down to say which was meant.

## Ingestion tiers

`make ingest` — the layered path (`CSV → tr_raw → tr_stg → tr_core`), separate
from the bulk loader that deploys. `make ingest ARGS=--corrupt` injects malformed
rows so you can watch them quarantine:

```
[WARN  ] INGESTION: project_key is unique in the batch - 1 row(s)
           4: appears 2 times
[REJECT] INGESTION: mandatory project fields are populated - 1 row(s)
           9003: missing id/status/portfolio
[REJECT] INGESTION: dates parse - 1 row(s)
           9001: unparseable date: 2026-13-45 / 2026-04-26
[REJECT] INGESTION: status is in the approved domain - 1 row(s)
           9002: unknown status: IN_PROGRESS
[WARN  ] INGESTION: no exact duplicate deliveries - 1 row(s)
           bec5966…: identical payload delivered 2 times
5 finding(s) quarantined; 3 row(s) held back from CORE, the clean majority continues
[PASS] CORE: all checks clean
[PASS] METRIC: all checks clean
→ 260 projects still land, CORE and METRIC clean
```

Severity is what makes a quarantine useful rather than annoying. `REJECT` rows
have no safe interpretation and never reach CORE; `WARN` rows are a problem with
the *delivery* that staging already resolves deterministically — dropping a
project over a duplicate the pipeline handled would lose good data. Treating
every finding as fatal is how teams end up disabling their own quality gates.

RAW keeps every column as `VARCHAR` on purpose: `2026-13-45` survives ingestion
intact, so "did the source send it wrong or did we transform it wrong?" is
answerable by diffing two layers instead of by arguing.

The staging SQL is **byte-identical across both engines**. DuckDB's `TRY_CAST` has
no PostgreSQL equivalent, so each engine defines the same four safe-cast helpers
([DuckDB macros](sql/06_functions_duckdb.sql) ·
[PostgreSQL functions](sql/06_functions_postgres.sql)) and
[06_staging.sql](sql/06_staging.sql) never forks. One small shim beats two copies
of the staging logic drifting apart — and a test runs the whole layered pipeline
on PostgreSQL to keep that claim honest.
