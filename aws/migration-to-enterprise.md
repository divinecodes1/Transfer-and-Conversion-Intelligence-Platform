# Migration to an Enterprise AWS Environment

The student deployment is the same architecture on the cheapest tier of each
service, so most of the path forward is **changing a variable, not changing a
design**. This says which is which.

---

## What changes by configuration

| Concern | Student | Enterprise | How |
|---|---|---|---|
| API scaling | Lambda, on demand | Lambda with provisioned concurrency, or Fargate | `api_memory_mb`, add `provisioned_concurrent_executions` |
| Database size | `db.t4g.micro`, single-AZ | `db.r6g.large`, Multi-AZ, read replica | `db_instance_class`, add `multi_az = true` |
| Backups | 1 day | 35 days + cross-region copy | `backup_retention_period` |
| Log retention | 14 days | 90+ days, exported to S3 | `log_retention_days` |
| Images | 3 kept, scan on push | immutable tags, signed, scanned continuously | ECR lifecycle + `image_tag_mutability` |
| Terraform state | local file | S3 + DynamoDB/lockfile | uncomment the backend in `providers.tf` |
| AI provider | `mock` | Bedrock, or Azure OpenAI via the OpenAI adapter | `ai_provider`, `ai_base_url` |

**Bedrock needs no new adapter.** `ai/gateway.py`'s OpenAI adapter is raw HTTP
against any `/chat/completions` endpoint.

---

## What has to be built

### 1. Private networking — the largest gap

Today RDS is publicly accessible and Lambda runs outside the VPC.

```text
VPC
 ├── public subnets    ALB, NAT gateways
 ├── private subnets   Lambda ENIs, Keycloak, RDS
 └── VPC endpoints     S3, ECR, SSM, CloudWatch (avoid NAT for AWS traffic)
```

**The catch:** a VPC-attached Lambda needs a NAT gateway (~$32/month per AZ) or
a VPC endpoint for every service it calls. That is precisely the trade that
makes it wrong for a student tier and right for production.

Order: private subnets → RDS `publicly_accessible = false` → VPC endpoints for
S3/ECR/SSM → NAT only for genuinely external calls (the model provider).

### 2. HTTPS for Keycloak

Today it serves port 8080 in the clear. Needs an ALB, an ACM certificate and a
domain name — roughly $16/month for the ALB. Until then, no real credentials.

### 3. Keycloak in a real HA shape

One instance with in-memory sessions. Production wants two or more behind the
ALB with an Infinispan cache stack, or ECS Fargate with a shared cache, and
`sticky` sessions disabled.

### 4. Oracle as the system of record

The master plan's target. The `sql/` files are already portable across
PostgreSQL and DuckDB because date arithmetic was kept portable deliberately —
Oracle is a **dialect change, not a redesign**.

What moves: `06_functions_postgres.sql` gets an Oracle sibling (the
DuckDB/PostgreSQL split already proves the shim pattern), `COUNT(*) FILTER` →
`COUNT(CASE WHEN ...)`, RLS → Oracle VPD, `psycopg2` → `oracledb` behind
`api/db.py` — which is already the only module that knows a driver exists.

The governed metric layer, the catalogue and every test move unchanged.

### 5. Airflow instead of EventBridge

`dags/transferops_pipeline.py` exists and `tests/orchestration_checks.py`
already asserts it parses, delegates and gates the run. The DAG calls the same
`etl/` entry points, so this is a scheduler swap — target MWAA.

### 6. ECS/EKS, if it earns its place

Move only when there is something Lambda cannot do: a request longer than 15
minutes, a persistent connection, a sidecar mesh, GPU scheduling. "It looks more
enterprise" is not a reason — and `kubernetes/transferops.yaml` plus
`tests/k8s_checks.py` already exist for when it becomes one.

---

## What does not change

- **The governed metric layer.** Engine-agnostic and database-portable.
- **The entitlement model.** Roles and entitlements are tables; only enforcement
  is engine-specific.
- **The AI fence.** Closed tool list, scope override, no metric leak — all
  application logic.
- **Every test suite.** 18 suites, 200+ assertions, none of which know which
  cloud they run in.
- **The console.** It talks to the governed API and nothing else.

That portability is the actual claim this repository makes. It has now been
deployed to two different clouds without the application layer changing at all —
the Azure stack ran the same images against Container Apps and Flexible Server;
this one runs them on Lambda and RDS.

---

## Sequencing

| Phase | Scope | Rough cost/month |
|---|---|---|
| 0 — Student | current | $0–20 |
| 1 — Hardened demo | private subnets + NAT, ALB/TLS for Keycloak, remote state | $80–150 |
| 2 — Pilot | WAF, Multi-AZ RDS, custom domain, GuardDuty | $400–700 |
| 3 — Production | Oracle, MWAA, multi-region, DR, full observability | enterprise |

Phase 1 closes the two honest gaps in [security.md](security.md) without a
rewrite, and is the one worth doing early.
