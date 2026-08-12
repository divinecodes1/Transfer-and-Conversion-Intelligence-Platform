# Transfer & Conversion Intelligence Platform — Refined Master Plan

> ⚠️ **Historical document — kept for provenance, not for accuracy.** This is the
> original scoping plan the build started from. It is deliberately *not* updated
> as the system changes, so the choices it proposes can still be compared against
> the choices that were actually made. Where it disagrees with the repository,
> the repository is right. For current state see [PLAN.md](PLAN.md) (the build
> sequence and its acceptance criteria) and the [README](../README.md).
>
> The clearest divergences: the BI layer was hand-built rather than Superset /
> Metabase / Streamlit, so the dashboards add zero dependencies; and a fenced
> model layer (`ai/`) was added above the deterministic assistant rather than
> instead of it.

## Infineon-Style Transfer-Project Performance Analytics Platform

> **Purpose:** Build a runnable enterprise-style reference implementation of the transfer-project reporting platform described in the interview.
>
> **Positioning:** This is an open, synthetic-data replica of the architectural pattern — not a claim to reproduce Infineon's internal production systems.

---

## 1. Executive Summary

The platform is best understood as a **transfer-project portfolio performance system**, not just a dashboard collection.

It should answer:

- How are transfer projects performing?
- How do forecasts compare with actual outcomes?
- How far have schedules moved from the original baseline?
- How does cycle-time distribution change across fiscal years?
- Which projects are delayed, ageing, unstable, or hard to predict?
- Can users get correct answers without already knowing the right dashboard filters?

The core architecture is:

```text
Sources
  ↓
RAW / STAGING
  ↓
Canonical CORE model
  ↓
Governed METRIC layer
  ↓
Reporting MARTS
  ↓
BI / Dashboards
  ↓
Read-only AI Assistant
```

**Master principle:** define every business metric once and reuse it everywhere — SQL, BI, APIs, tests, and AI.

---

## 2. What the Demo Represents

### Interview-supported concepts

- transfer-project portfolio reporting
- forward-looking and backward-looking performance
- forecast cycle time vs historical cycle time
- original schedule vs latest schedule
- fiscal-year comparison
- cycle-time distribution / box plots
- filtering by relevant cohorts
- clearer data / calculation / reporting separation
- future self-explaining AI / agent functionality

### Replica implementation choices

- PostgreSQL for deployment
- DuckDB for fast local tests
- Oracle-compatible modelling patterns
- FastAPI
- Airflow
- Keycloak
- Superset / Metabase / Streamlit
- Qdrant
- LangChain-style constrained agent
- Prometheus / Grafana
- Docker
- kind / k3d Kubernetes
- GitHub Actions

These are **reference-implementation choices**, not claims about hidden Infineon infrastructure.

---

## 3. Infineon-to-Replica Mapping

| Enterprise / interview concept | Replica |
|---|---|
| Relational analytical database | PostgreSQL / DuckDB |
| Oracle-style warehouse architecture | Layered schemas, SQL views, materialized views |
| BI Portal / Tableau | Superset / Metabase / Streamlit |
| Original vs latest schedule | Immutable schedule revision history |
| Forecast vs historical performance | Forecast snapshots + actual outcomes |
| Fiscal-year box plots | Distribution mart with P25/P50/P75/P90 |
| Filters | Governed dimensions |
| Self-explaining reporting | Read-only AI analytics agent |
| Corporate SSO / RBAC | Keycloak + DB row filtering |
| Platform monitoring | Prometheus + Grafana |

---

## 4. Non-Negotiable Design Principles

1. Evolutionary, not rip-and-replace.
2. Preserve history explicitly.
3. Metrics before dashboards.
4. One governed definition per KPI.
5. BI visualizes; BI does not redefine core metrics.
6. Security must exist below the UI.
7. LLMs handle language and planning; deterministic systems calculate.
8. The first AI release is read-only.
9. Every important number is regression-tested.
10. Build one complete vertical slice before adding infrastructure depth.

---

## 5. Final Target Architecture

```text
┌────────────────────────────────────────────────────────────┐
│ SOURCE / INPUT                                             │
│ Projects · Schedules · Milestones · Forecasts · Actuals   │
│ Fiscal reference data · User entitlements                 │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ INGESTION + DATA QUALITY                                   │
│ Validate · deduplicate · normalize · audit · quarantine   │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ RAW                                                        │
│ Immutable source-faithful records                          │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ STAGING                                                    │
│ Typing · standardization · source cleanup                  │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ CORE                                                       │
│ Project · Milestone · Schedule Revision · Forecast         │
│ Snapshot · Fiscal Calendar · Site · Portfolio              │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ METRIC / SEMANTIC                                          │
│ Cycle Time · Schedule Deviation · Forecast Accuracy        │
│ Throughput · WIP · Replan · Stage Time · Distribution     │
└──────────────────────────┬─────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│ MARTS                                                      │
│ Project Status · Timeline · Cycle Distribution             │
│ Forecast Accuracy · Portfolio Period · Data Quality        │
└─────────────────┬──────────────────────┬───────────────────┘
                  │                      │
                  ↓                      ↓
        ┌──────────────────┐   ┌─────────────────────────┐
        │ BI / PORTAL      │   │ Governed Analytics API  │
        │ dashboards       │   │ read-only metric tools  │
        └────────┬─────────┘   └────────────┬────────────┘
                 │                          ↓
                 │               ┌───────────────────────┐
                 │               │ AI / AGENT            │
                 │               │ intent + filters      │
                 │               │ semantic retrieval    │
                 │               │ explanation/provenance│
                 │               └────────────┬──────────┘
                 └──────────────┬─────────────┘
                                ↓
                         BUSINESS USERS
```

---

## 6. Repository Structure

```text
transferops/
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── MASTER_PLAN.md
│   ├── architecture.md
│   ├── data_model.md
│   ├── metrics.md
│   ├── security.md
│   ├── live_vs_extract.md
│   ├── demo_script.md
│   └── interview_one_pager.md
├── data/
│   ├── generate.py
│   ├── raw/
│   └── golden/
├── sql/
│   ├── 00_schemas.sql
│   ├── 01_raw.sql
│   ├── 02_staging.sql
│   ├── 03_core.sql
│   ├── 04_metric_catalogue.sql
│   ├── 05_metrics.sql
│   ├── 06_marts.sql
│   ├── 07_materialized_views.sql
│   └── 08_rls.sql
├── legacy/
│   └── v0_legacy.sql
├── etl/
│   ├── ingest.py
│   ├── transform.py
│   ├── dq_checks.py
│   └── run.py
├── airflow/dags/
├── services/
│   ├── gateway/
│   ├── project/
│   ├── analytics/
│   └── ai/
├── agent/
│   ├── schema.py
│   ├── resolver.py
│   ├── executor.py
│   ├── retrieval.py
│   ├── explain.py
│   ├── policy.py
│   └── evals/
├── bi/
│   ├── dashboards/
│   ├── datasource/
│   └── portal/
├── security/keycloak/
├── observability/
│   ├── prometheus/
│   ├── grafana/
│   └── otel/
├── kubernetes/
├── tests/
└── .github/workflows/
```

---

## 7. Canonical Data Model

### Project

```text
project_key
project_id
project_name
transfer_type
portfolio
source_site
target_site
product_family
complexity_class
status
authorised_start_date
actual_start_date
actual_finish_date
created_at
```

### Milestone

```text
milestone_key
milestone_code
milestone_name
sequence_no
```

### Schedule Revision

```text
project_key
revision_id
revision_timestamp
revision_reason
planned_start
planned_finish
forecast_finish
is_baseline
is_rebaseline
approved_by
```

### Project Snapshot

```text
project_key
snapshot_date
status
forecast_finish
current_stage
risk_status
progress_pct
```

### Forecast Snapshot

```text
project_key
snapshot_date
forecast_finish
forecast_cycle_time_days
forecast_horizon_days
```

### Fiscal Calendar

```text
calendar_date
fiscal_week
fiscal_month
fiscal_quarter
fiscal_year
```

---

## 8. Historical Model Rule

The model must preserve:

```text
original baseline
≠ approved rebaseline
≠ latest plan
≠ current forecast
≠ actual outcome
```

This lets the platform answer:

- What did we originally plan?
- What changed?
- When did it change?
- How many times was the schedule revised?
- What forecast existed 90/60/30 days before completion?
- What was the final result?

---

## 9. Canonical Metric Set

### Tier 1 — Must Have

| Metric | Definition |
|---|---|
| Actual Cycle Time | `actual_finish - actual_start` |
| Forecast Cycle Time | `forecast_finish - actual_start` |
| Schedule Deviation | `latest_planned_finish - baseline_finish` |
| Completion Variance | `actual_finish - baseline_finish` |
| Forecast Error | `actual_finish - forecast_finish_at_horizon` |
| Throughput | completed projects per fiscal period |
| WIP | open qualifying projects |
| WIP Age | `snapshot_date - actual_start` |

### Tier 2 — Strong Demo Metrics

- On-Time Completion Rate
- Replan Rate
- Stage Cycle Time
- Cycle-Time IQR
- P90 Cycle Time
- Forecast Bias
- Median Absolute Forecast Error
- Forecast accuracy by 30/60/90-day horizon

---

## 10. DORA-Inspired Framing

Use DORA as a **measurement philosophy**, not a literal metric copy.

```text
DORA:
Throughput + Instability
      ↓
Understand delivery
      ↓
Improve
      ↓
Re-measure

Transfer & Conversion Intelligence Platform:
Flow + Predictability + Stability
      ↓
Understand transfer execution
      ↓
Find bottlenecks / forecasting problems
      ↓
Improve
      ↓
Re-measure
```

Conceptual mapping:

| DORA concept | Transfer & Conversion Intelligence Platform analogue |
|---|---|
| Change lead time | Transfer cycle time |
| Deployment frequency | Transfer throughput |
| Recovery time | Deviation recovery |
| Change fail rate | Schedule miss / deviation rate |
| Rework rate | Replan / corrective rework rate |

Preferred wording:

> **DORA-inspired Transfer Performance Analytics**

---

## 11. Metric Governance

Every Tier-1 KPI must contain:

```text
metric_code
business_name
definition
formula
grain
unit
population
exclusions
valid_dimensions
owner
version
effective_from
known_limitations
```

Example:

```yaml
metric_code: ACTUAL_TRANSFER_CYCLE_TIME
business_name: Actual Transfer Cycle Time
definition: Calendar days between actual start and actual completion
grain: completed transfer project
unit: days
population: completed non-cancelled projects
dimensions:
  - fiscal_year
  - transfer_type
  - source_site
  - target_site
  - portfolio
version: 1.0
owner: transfer_management
```

---

## 12. Data Quality

### Ingestion

- uniqueness
- completeness
- type validation
- status/domain validation
- deduplication
- freshness

### Core

- `actual_finish >= actual_start`
- milestone sequence valid
- baseline exists where required
- frozen baseline is immutable
- revision timestamps are monotonic
- foreign keys resolve
- one snapshot/project/day

### Metric

- cycle time is non-negative
- completion variance only exists for completed projects
- throughput reconciles to detail
- distribution population reconciles
- forecast error requires an actual outcome

---

## 13. Golden-Project Regression Set

Maintain 20–50 projects covering:

- normal on-time
- late
- early
- cancelled
- multiple revisions
- approved rebaseline
- missing forecast
- long-running
- cross-fiscal-year
- outlier
- rework
- open/in-progress

Every metric change reruns this suite.

---

## 14. Before / After Modernization

Create:

```text
legacy/v0_legacy.sql
```

The legacy version deliberately includes:

- inline KPI formulas
- magic filters
- duplicated logic
- current-state schedule only
- poor separation

Then show:

```text
V0 legacy result
      ==
V1 governed result
```

on the golden portfolio.

The business number matches, but V1 is:

```text
historical
testable
versioned
reusable
secure
AI-ready
```

This is one of the highest-value demo moments.

---

## 15. BI Design

### Management Dashboard

Cards:

- Total Projects
- Active
- Completed
- At Risk
- Delayed
- Median Cycle Time
- Median Schedule Deviation
- Forecast Accuracy

Charts:

- portfolio health
- throughput trend
- on-time rate
- cycle-time trend
- at-risk portfolio

### Technical / PMO Dashboard

- FY cycle-time box plots
- original vs latest schedule
- forecast vs actual
- forecast accuracy by horizon
- schedule revision history
- milestone stage cycle time
- project drill-down
- data-quality health

Filters:

- Fiscal Year
- Transfer Type
- Portfolio
- Source Site
- Target Site
- Product Family
- Status
- Complexity Class

---

## 16. Live vs Extract Strategy

Choose based on:

```text
freshness value
vs
query cost + concurrency + performance
```

| View | Suggested mode |
|---|---|
| Current project status | Live |
| Urgent operational view | Live |
| Multi-year box plots | Pre-aggregated / extract |
| Portfolio trends | Extract |
| Executive periodic report | Extract |
| Reconciliation/debug | Live |

---

## 17. Security Model

Separate:

```text
Authentication → Who are you?
Role           → What type of user are you?
Entitlement    → Which data may you see?
Action         → What may you do?
```

Suggested roles:

```text
TRANSFER_VIEWER
TRANSFER_ANALYST
TRANSFER_MANAGER
REPORT_DEVELOPER
DATA_ENGINEER
PLATFORM_ADMIN
```

Entitlement dimensions:

```text
portfolio
site
transfer_type
project
```

The AI assistant receives the same resolved security context.

---

## 18. Demo Identity Flow

```text
Keycloak
   ↓
OIDC token
   ↓
FastAPI
   ↓
resolved identity / role / entitlement
   ↓
DB row filtering
   ↓
BI + Agent
```

Use fictional accounts:

```text
manager.demo
analyst.demo
developer.demo
```

---

## 19. AI Assistant

### Governing rule

> The model does not define metrics, decide permissions, or perform business arithmetic when deterministic tools can do it.

Flow:

```text
Question
  ↓
Intent parser
  ↓
Metric resolver
  ↓
Filter resolver
  ↓
Authorization check
  ↓
Governed query object
  ↓
Policy validator
  ↓
Approved executor
  ↓
Result validator
  ↓
Explanation + provenance
```

---

## 20. Metric Query Object

```json
{
  "metric": "ACTUAL_TRANSFER_CYCLE_TIME",
  "aggregation": "median",
  "group_by": ["fiscal_year", "transfer_type"],
  "filters": {
    "status": ["COMPLETED"]
  }
}
```

The backend converts this object into parameterized SQL.

---

## 21. Agent Tools

```python
get_metric()
compare_metric()
get_distribution()
get_project()
get_schedule_history()
get_delayed_projects()
list_outliers()
explain_dashboard()
search_metric_definition()
```

Avoid unrestricted text-to-SQL.

---

## 22. RAG / Semantic Knowledge

Store:

- metric definitions
- metric aliases
- business glossary
- fiscal rules
- valid filters
- dashboard descriptions
- lineage
- approved examples
- known limitations

Suggested Qdrant collections:

```text
metric_definitions
dashboard_metadata
architecture_docs
user_guides
```

---

## 23. AI Response Contract

Every numerical answer should show:

```text
Metric
Metric version
Definition
Population
Filters
Comparison period
Data as-of
Project count
Tool/source
```

This is what makes the agent genuinely self-explaining.

---

## 24. AI Security

Treat as untrusted:

```text
user input
retrieved text
project comments
LLM output
```

Trusted:

```text
policy engine
metric catalogue
authorization layer
query executor
```

Agent DB access:

```text
READ ONLY
allowed schemas only
no DDL
no INSERT/UPDATE/DELETE
timeout
row limit
RBAC independent of prompt
```

---

## 25. Observability

### Pipeline

- last successful load
- duration
- processed/rejected rows
- source freshness
- duplicates
- null-rate trend
- failures

### DB

- query latency
- materialized-view refresh
- slow queries
- storage growth

### BI

- dashboard load time
- failed refreshes
- usage
- unused dashboards

### AI

- latency
- tool success
- metric-resolution accuracy
- filter-resolution accuracy
- numeric accuracy
- abstention
- prompt-injection detections
- security violations
- human corrections

---

## 26. Airflow

One primary DAG:

```text
ingest_transfer_data
        ↓
validate_raw
        ↓
build_staging
        ↓
build_core
        ↓
calculate_metrics
        ↓
build_marts
        ↓
refresh_semantic_index
```

Demonstrate:

- dependencies
- retries
- failed DQ batch
- successful rerun
- backfill concept

---

## 27. Kubernetes

Use kind or k3d.

Deploy only components that remain stable:

```text
gateway
analytics-service
ai-service
dashboard
qdrant
keycloak
```

PostgreSQL and Airflow may remain in Docker Compose if moving them into Kubernetes risks demo stability.

---

## 28. CI/CD

```text
push
 ↓
lint
 ↓
unit tests
 ↓
SQL tests
 ↓
golden-project tests
 ↓
RBAC tests
 ↓
agent evals
 ↓
Docker build
 ↓
security scan
```

---

## 29. Fine-Tuning

Fine-tuning is **not critical path**.

If included:

- use a small model
- use LoRA/QLoRA
- train only on synthetic KPI explanation examples
- keep the full system functional without the tuned model

Production default:

```text
governed tools + RAG
```

Fine-tuning is only an experiment.

---

## 30. Current Project State

According to the existing project plan, Phase 1 is complete:

- data foundation
- governed metric core
- metric dictionary
- marts
- synthetic project generation
- schedule revisions
- project snapshots
- golden reconciliation
- DuckDB development
- PostgreSQL deployment

Therefore the next work should maximize **demo leverage**.

---

## 31. Refined Critical Path

```text
1. Foundation                         ✅ done
       ↓
2. Complete metrics + v0 legacy contrast
       ↓
3. Management + technical BI
       ↓
4. Self-explaining agent
       ↓
5. RBAC + audit
       ↓
6. Airflow + observability
       ↓
7. Kubernetes + CI/CD
       ↓
8. Polish + interview package
```

Airflow, Kubernetes, extra microservices, and fine-tuning must never block the core demonstration.

---

## 32. 48-Hour Build Plan

### Day 1 — Build the Winning Demo

#### 08:00–10:00 — Stabilize Existing Foundation

- run all current tests
- verify DuckDB/PostgreSQL paths
- clean repo
- freeze a baseline commit

#### 10:00–13:00 — Complete Metrics

Add:

- forecast accuracy by horizon
- WIP / WIP age
- replan rate
- stage cycle time
- IQR / P90
- metric versioning

#### 13:00–15:00 — Build Legacy Contrast

Create `legacy/v0_legacy.sql`.

Validate:

```text
legacy number == governed number
```

for the golden set.

#### 15:00–18:00 — BI

Build:

1. Management dashboard
2. Technical / PMO dashboard

Must show:

- FY cycle-time box plot
- original vs latest
- forecast vs actual
- portfolio health

#### 18:00–21:00 — Agent Core

Build:

- query object
- metric resolver
- filter resolver
- deterministic executor
- response contract

Test:

```text
What is cycle time?
Compare FY25 vs FY26.
Show delayed projects.
Which transfer type has the highest P90?
```

#### 21:00–23:00 — Minimum Security

- Keycloak or lightweight JWT
- analyst and manager personas
- portfolio scoping
- one denied cross-portfolio test

### End-of-Day-1 Gate

Must have:

```text
DATA
METRICS
BEFORE/AFTER
DASHBOARD
AGENT
RBAC
```

---

### Day 2 — Enterprise Depth

#### 07:00–09:00 — Agent Evaluation

Create 20–40 benchmark questions with expected:

```text
metric
filters
numeric result
abstention behavior
```

#### 09:00–11:00 — RAG

Index:

- metric dictionary
- dashboard metadata
- business glossary
- fiscal rules

#### 11:00–13:00 — Airflow

Build the end-to-end DAG.

#### 13:00–15:00 — Audit + Observability

- agent audit table
- service metrics
- Prometheus
- one Grafana dashboard

#### 15:00–17:00 — Kubernetes

Deploy stable services only.

#### 17:00–18:00 — CI/CD

Get GitHub Actions green.

#### 18:00–20:00 — Documentation

Finish:

- README
- architecture
- metric catalogue
- security
- one-page proposal
- demo script

#### 20:00–21:00 — Fine-Tuning Stretch

Only if all core items are green.

#### 21:00–23:00 — Rehearsal

No new features after 22:00.

---

## 33. Minimum Winning Demo

If time becomes tight, stop at:

1. synthetic transfer data
2. schedule history
3. metric catalogue
4. cycle-time + schedule-deviation metrics
5. golden reconciliation
6. legacy-vs-modern comparison
7. management dashboard
8. fiscal-year box plot
9. read-only AI assistant
10. metric + filters + timestamp in answers
11. one RBAC demo
12. clean README + architecture diagram

A smaller complete platform is stronger than fifteen half-working technologies.

---

## 34. Stretch Priority

```text
1. Airflow
2. Prometheus / Grafana
3. Kubernetes
4. Portal embedding
5. Extra microservices
6. Fine-tuning
```

---

## 35. Definition of Done

### Data

- [ ] 100–300 synthetic projects
- [ ] schedule revisions
- [ ] forecast snapshots
- [ ] milestone events
- [ ] fiscal calendar
- [ ] DQ tests

### Metrics

- [ ] cycle time
- [ ] schedule deviation
- [ ] completion variance
- [ ] forecast error
- [ ] throughput
- [ ] WIP / WIP age
- [ ] P50/P75/P90
- [ ] replan rate
- [ ] metric versioning

### BI

- [ ] management dashboard
- [ ] technical dashboard
- [ ] FY box plot
- [ ] original-vs-latest
- [ ] forecast view
- [ ] drill-down

### AI

- [ ] metric resolution
- [ ] filter resolution
- [ ] deterministic tools
- [ ] RAG definitions
- [ ] filters shown
- [ ] data timestamp shown
- [ ] read-only enforcement
- [ ] injection test

### Security

- [ ] identity provider
- [ ] roles
- [ ] entitlements
- [ ] cross-scope denial

### Platform

- [ ] Docker Compose
- [ ] Airflow DAG
- [ ] health endpoints
- [ ] CI pipeline
- [ ] observability
- [ ] Kubernetes if stable

### Interview Package

- [ ] one-page proposal
- [ ] simplified architecture
- [ ] full architecture
- [ ] 5-minute demo runbook
- [ ] three-week production pilot
- [ ] reproducible README

---

## 36. Five-Minute Demo

### 0:00–0:40 — Problem

> This is a project-performance system, not just a visualization layer. I focused on preserving history, defining metrics once, and making the reporting self-explaining.

### 0:40–1:20 — Legacy vs Governed

Show the same number from `v0_legacy` and the governed metric layer.

### 1:20–2:10 — Dashboard

Show:

- portfolio health
- FY box plot
- schedule deviation
- forecast accuracy

### 2:10–3:20 — Agent

Ask:

> Which transfer type has the highest median cycle time in FY26?

Show:

- metric
- definition
- filters
- result
- data timestamp

### 3:20–4:00 — RBAC

Switch persona and show restricted data.

### 4:00–4:40 — Engineering Quality

Show tests, Airflow, audit, CI.

### 4:40–5:00 — Close

> BI and AI both consume the same governed metric foundation. The agent does not invent business logic and cannot bypass security.

---

## 37. Strong Interview Statement

> **I separated project data, business calculations, and presentation so metrics like cycle time are defined once and reused everywhere. Then I put a read-only, permission-aware AI assistant on top of those trusted metrics so users can ask questions without already knowing the exact filters.**

---

## 38. Production Evolution

### 0–3 months

```text
source inventory
lineage
metric glossary
golden projects
one production KPI family
```

### 3–6 months

```text
clean data foundation
schedule history
DQ framework
RBAC
first migrated dashboard
```

### 6–12 months

```text
metric standardization
portfolio marts
dashboard migration
dual-run validation
observability
```

### 12–18 months

```text
semantic metadata
read-only AI pilot
agent evaluation
portal integration
```

### 18–24 months

```text
broader AI adoption
advanced forecasting
agent governance
continuous improvement
```

---

## 39. Final Master Principle

```text
Historically grown reporting logic
              ↓
Clean historical data foundation
              ↓
One governed metric system
              ↓
Consistent BI
              ↓
Safe self-explaining analytics
```

> **Transfer & Conversion Intelligence Platform is a governed transfer-performance analytics platform where project history is preserved, KPIs are defined once, dashboards consume trusted metrics, and a secure AI assistant helps users navigate and understand the reporting system.**
