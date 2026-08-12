# How this replica maps to Infineon's Transfer & Conversion Management system

This project is an **open-stack replica** of the reporting platform described in
interview, built to the architecture in the modernisation spec. It mirrors the
*pattern* 1:1 in free, runnable tools rather than copying the licensed stack — which
demonstrates understanding of the architecture, not just one vendor.

| Infineon (as described in interview) | This replica | Why it's equivalent |
| --- | --- | --- |
| Oracle databases | PostgreSQL (DuckDB for dev/tests) | Same relational/SQL model; Postgres has materialised views + partitioning too. Migration to Oracle is a dialect change, not a redesign. |
| BI Portal + Tableau | Reporting marts + a React product console (`web/`), with a static hand-built dashboard (`bi/`) as the reference implementation | KPI logic lives in the metric layer; both clients only visualise, and a test asserts neither holds SQL or a definition. |
| Excel macros / manual rollups | Python ETL + governed SQL metric layer | The "renovation": logic out of spreadsheets/workbooks into one calc layer. |
| Charts: cycle-time forecast vs history | `v_project_cycle_time` + `v_forecast_cycle_time` | Actual vs forecast cycle time, both preserved. |
| Charts: original vs latest schedule | `v_schedule_deviation` over `fact_schedule_revision` | Baseline is immutable; latest is newest revision. |
| Charts: box plots across fiscal years | `mart_cycle_time_distribution` (P25/P50/P75/P90) | Distribution, not just averages. |
| Filters | Governed dimensions on the marts, whitelisted in the API | Same filter model the assistant resolves automatically. |
| Oracle VPD row-level security | PostgreSQL row-level security on `tr_core.dim_project` | Enforcement below the visualisation layer, not a workbook filter. |
| Corporate SSO | Keycloak realm (`keycloak/realm-export.json`) | OIDC identity; entitlements still resolve from `tr_gov`. |
| "First attempts with LLM/agentic" | Catalogue-bound read-only assistant (`agent/`), plus an optional fenced model layer (`ai/`) | Queries the metric catalogue, never raw SQL. The model layer phrases governed numbers and calls governed endpoints; it holds no database handle. |
| Generated summaries / narratives for management | `ai/insights.py` → `tr_ai.insight`, stamped with the warehouse vintage | Model output is cached and expiring, entitlement-scoped, and never registered as a metric. |
| Their own monitoring | Prometheus/Grafana (`observability/`) | Monitors pipeline freshness, API latency and adoption of the platform + assistant. |

## Fiscal calendar
Infineon's fiscal year starts **1 October** (FY26 = Oct 2025 – Sep 2026). The
`dim_fiscal_date` generator implements exactly this, so fiscal-year groupings match.

## Domain vocabulary used in the synthetic data
- **Transfer types:** FAB_TO_FAB, INT_TO_FOUNDRY, FOUNDRY_TO_INT, ASSY_MOVE, NODE_CONVERSION
- **Sites:** Villach, Dresden, Regensburg, Kulim, Batam, Melaka, Wuxi, Dublin
- **Portfolios:** PF_AUTO, PF_POWER, PF_IOT (Automotive / Green Industrial Power / Connected Secure Systems)
- **Milestones:** Design Transfer → Tapeout → Qual Lots → Reliability Qual → Customer Qual → Production Release

These are illustrative, not Infineon-internal facts — they exist so the metrics
have realistic shape to demonstrate.

## Demo accounts
Fictional, and never real identities: `admin.demo`, `analyst.demo`,
`manager.auto` (PF_AUTO only), `manager.power` (PF_POWER only), `viewer.demo`
(PF_IOT only). Two managers asking the identical question get different answers,
enforced by the database rather than by the dashboard.
