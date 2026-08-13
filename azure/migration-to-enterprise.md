# Migration to an Enterprise Azure Environment

The student deployment is not a throwaway that would be rebuilt for production.
It is the same architecture on the cheapest tier of each service, which means
most of the path forward is **changing a SKU, not changing a design**.

This document says which is which.

---

## What changes by configuration

These need no application change and no architectural rework.

| Concern | Student | Enterprise | How |
|---|---|---|---|
| API scaling | Consumption, min 0 | Dedicated workload profile, min 2 | `api_min_replicas`, add a profile to the environment |
| Keycloak | min 0, single replica | min 2 + Infinispan cache stack, or Entra ID | `keycloak_min_replicas`, JGroups config |
| Database size | B1ms, 32 GB | General Purpose, HA, read replica | `postgres_sku_name`, add `high_availability` |
| Backups | 7 days, local | 35 days, geo-redundant | `postgres_backup_retention_days`, `geo_redundant_backup_enabled` |
| Log retention | 30 days, capped 0.1 GB/day | 90+ days, uncapped | `log_retention_days`, `log_daily_quota_gb` |
| Images | public GHCR | ACR Premium, scanned, signed | `use_acr = true` |
| Terraform state | local file | storage account + state locking | uncomment the backend in `providers.tf` |
| AI provider | `mock` | Azure OpenAI | `ai_provider = "openai"`, `ai_base_url` at the deployment |

**Azure OpenAI needs no new adapter.** `ai/gateway.py`'s OpenAI adapter is raw
HTTP against any `/chat/completions` endpoint, so pointing `ai_base_url` at an
Azure OpenAI deployment is a configuration change.

---

## What has to be built

Real work, in rough order of value.

### 1. Private networking

The largest single gap. Today the database is on public networking with firewall
rules.

```text
VNet
 ├── subnet: container-apps   (delegated, VNet-injected environment)
 ├── subnet: private-endpoints
 │     ├── PostgreSQL private endpoint
 │     ├── Key Vault private endpoint
 │     └── Storage private endpoint
 └── Private DNS zones
```

**The catch:** a VNet-integrated Container Apps environment forfeits the
Consumption-only profile and therefore scale-to-zero. This is precisely the trade
that makes it wrong for a student tier and right for production.

### 2. Edge protection

```text
Front Door Premium
 ├── WAF (OWASP ruleset)
 ├── rate limiting
 ├── custom domain + managed certificate
 └── origin: Static Web App + Container App (private link)
```

### 3. Oracle as the system of record

The master plan's target. The `sql/` files are portable across PostgreSQL and
DuckDB today because date arithmetic was kept portable deliberately — Oracle is a
**dialect change, not a redesign**.

What moves:
- `06_functions_postgres.sql` → an Oracle equivalent (the DuckDB/PostgreSQL split
  already proves the shim pattern works)
- `PERCENTILE_CONT ... WITHIN GROUP` — same syntax in Oracle
- `COUNT(*) FILTER (WHERE ...)` → `COUNT(CASE WHEN ... THEN 1 END)`
- Row-level security → Oracle VPD / Real Application Security
- `psycopg2` → `oracledb` behind `api/db.py`, which is already the only module
  that knows a driver exists

The governed metric layer, the catalogue and every test move unchanged.

### 4. Airflow instead of Container Apps Jobs

`dags/transferops_pipeline.py` already exists and `tests/orchestration_checks.py`
already asserts it parses, delegates and gates the run. The DAG delegates to the
same `etl/` entry points the job calls, so this is a scheduler swap.

Target: Azure Data Factory Managed Airflow, or Airflow on AKS.

### 5. AKS, if it earns its place

`kubernetes/transferops.yaml` exists and `tests/k8s_checks.py` asserts the
manifests parse, probe, limit and lock down. The migration is real but not
speculative.

Move only when there is something Container Apps cannot do: multi-service mesh,
custom operators, GPU scheduling, or an existing platform team's tooling. "It
looks more enterprise" is not a reason — Container Apps *is* Kubernetes
underneath.

### 6. Enterprise identity

If the organisation mandates it, Keycloak can federate to Entra ID as an identity
broker, keeping the realm's roles and themes while delegating authentication.

`api/auth.py` verifies any OIDC issuer's tokens; the change is configuration plus
a realm identity-provider setup.

> For this project, **Keycloak is the identity provider and stays that way**. The
> branded realm, self-registration, verification and recovery flows are part of
> what the platform demonstrates.

---

## What does not change

Worth stating, because it is the point of the architecture:

- **The governed metric layer.** `tr_gov.metric_definition` and `tr_metric` are
  database-portable and engine-agnostic.
- **The entitlement model.** Roles and data entitlements are tables; only the
  enforcement mechanism is engine-specific.
- **The AI fence.** Closed tool list, scope override, no metric leak — all
  application logic.
- **Every test suite.** 18 suites, 200+ assertions, none of which know which
  cloud they are running in.
- **The console.** It talks to the governed API and nothing else.

---

## Sequencing

| Phase | Scope | Rough cost/month |
|---|---|---|
| 0 — Student | current | 0–15 USD |
| 1 — Hardened demo | private endpoints, remote state, ACR, min replicas 1 | 80–150 USD |
| 2 — Pilot | Front Door + WAF, HA database, custom domain, Defender | 400–700 USD |
| 3 — Production | Oracle, Airflow, multi-region, DR, full monitoring | enterprise |

Phase 1 is the one worth doing early: it closes the honest gaps in
[security.md](security.md) without a rewrite.
