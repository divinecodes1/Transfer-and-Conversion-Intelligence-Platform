# AWS Architecture — Student Tier

> Production-quality architectural thinking without production-level spending.

Seven services, one region, one Terraform state. Everything either scales to
zero, sits in an always-free tier, or is the smallest instance its service
offers.

---

## The deployed shape

```text
                            INTERNET
                                │
            ┌───────────────────┼────────────────────┐
            ▼                   ▼                    ▼
   ┌─────────────────┐  ┌────────────────┐  ┌──────────────────┐
   │ CloudFront      │  │ Lambda         │  │ EC2 t3.micro     │
   │   → S3 (private)│  │ Function URL   │  │ Keycloak         │
   │ the console     │  │ FastAPI        │  │ always warm      │
   │ 1TB/mo free     │  │ scales to ZERO │  │ free 750h/mo     │
   └─────────────────┘  └───────┬────────┘  └────────┬─────────┘
                                │                    │
                                ▼                    ▼
                       ┌──────────────────────────────────┐
                       │ RDS PostgreSQL db.t4g.micro      │
                       │   ├── transferops (warehouse)    │
                       │   └── keycloak                   │
                       └──────────────────────────────────┘
                                │
   ┌────────────────┐  ┌────────┴────────┐  ┌──────────────────┐
   │ S3 documents   │  │ EventBridge     │  │ SSM Parameter    │
   │ reports/exports│  │  → Lambda       │  │ Store (free)     │
   │ lifecycle rules│  │ nightly refresh │  │ SecureStrings    │
   └────────────────┘  └─────────────────┘  └──────────────────┘

          CloudWatch Logs, 14-day retention
          IAM OIDC provider → role assumed by GitHub Actions
```

**Absent on purpose:** NAT gateway, ALB, ECS, EKS, Aurora, ElastiCache, Secrets
Manager, WAF, a second region. Each is a real production component and each is a
standing charge measured in tens of dollars a month. See
[migration-to-enterprise.md](migration-to-enterprise.md).

---

## Why each choice

### Lambda for the API — the reason this is nearly free

Lambda scales to zero *properly*: not "one small instance", actually zero. The
first million requests a month are free **forever**, not for twelve months.

**The application does not know it is on Lambda.** AWS Lambda Web Adapter
(`infrastructure/docker/lambda/Dockerfile`) is an internal extension that
accepts the invocation and replays it as an ordinary HTTP request against
`127.0.0.1:8000` — so the image runs the same `uvicorn api.main:app` that runs
locally, with no Mangum, no handler function, and no change to `api/main.py`.

That matters beyond convenience. `tests/api_checks.py` drives the real ASGI app;
if the deployment ran a different entry point, the contract those tests assert
would stop being the contract in production.

A **Function URL** rather than API Gateway: HTTPS, a stable hostname, and no
per-request charge on top of Lambda's own. API Gateway would add ~$1 per million
requests for usage plans and request validation this demo does not use.

### EC2 for Keycloak — where AWS beats the previous Azure design

Keycloak is a stateful JVM. It cannot scale to zero without dropping sessions,
and it takes 40–60 seconds to cold start. On Azure Container Apps that left two
bad options:

- hold a replica warm — roughly **$34/month**, a third of the credit, spent
  almost entirely on idle time, or
- accept a **40–60 second wait** on the first sign-in of the day

A `t3.micro` is 750 hours a month free on the legacy tier — more hours than a
month contains. It simply runs. **Always warm, no cold start, and no bill.**

An Elastic IP keeps the issuer URL stable across a stop/start; without it the
public IP changes and every previously issued token fails issuer validation.

`x86_64` rather than Graviton: GitHub's runners are x86, and an arm64 image
would have to be built under QEMU. Both are equally free on the tier that
matters.

### One RDS instance, two databases

`transferops` (the warehouse) and `keycloak` share one `db.t4g.micro`. RDS bills
per **instance**, so co-tenanting costs nothing while a second instance would
double the largest standing charge. The isolation that matters — separate
databases, separate credentials, no shared tables — is preserved.

### S3 + CloudFront for the console

The console is a Vite SPA: static files, no server runtime. CloudFront rather
than an S3 website endpoint for one non-negotiable reason — **S3 website
endpoints are HTTP only**, and the console carries a bearer token on every API
call. CloudFront gives HTTPS on its default domain for nothing.

The bucket stays private; CloudFront reaches it through Origin Access Control,
so there is no public bucket policy to get wrong.

### SSM Parameter Store, not Secrets Manager

Secrets Manager is $0.40 per secret per month. Seven secrets is ~$2.80/month —
nearly 10% of a $30 budget, permanently, for rotation this demo does not do. SSM
standard parameters are free, including SecureString.

### GitHub OIDC → IAM — the thing Azure could not do

The Azure deployment ended with **CI unable to deploy at all**. Federated login
there needs an Entra app registration; a university tenant sets
`allowedToCreateApps = false`; and owning the whole subscription did not help,
because ARM rights and directory rights are separate concerns.

On AWS the equivalent is an IAM OIDC identity provider and an IAM role, both
**inside this account**, created by the same credentials that create everything
else. No directory, no tenant policy, no administrator.

Still no access key: GitHub mints a short-lived token whose subject must match
this repository and the `production-demo` environment exactly.

---

## What the application already brought

Most of the "AI-assisted platform" was built before any cloud was involved and
is not re-implemented here:

| Capability | Where it lives |
|---|---|
| KPI semantic layer | `tr_gov.metric_definition` + `sql/03_metric_views.sql`, with a gate proving catalogue and implementation agree |
| AI governance | the `ai/` fence — closed tool list, caller scope overriding model arguments, hallucinated ids dropped |
| Historical similarity **without an LLM** | `tr_metric.v_transfer_similarity` — deterministic, four published weights |
| Predictive risk **without an LLM** | `ai/risk.py`, fenced into `tr_ai` so a model's opinion cannot acquire a metric code |
| Readiness engine | `sql/13_readiness_network.sql`, weights stored as data |
| Row-level entitlement | `sql/10_rls.sql`, forced RLS, non-superuser reader |

The cloud layer hosts this platform. It does not reinvent it.

---

## Divergences from the master plan

| Plan says | Deployed as | Why |
|---|---|---|
| Next.js | Vite + React SPA | What the repo is. S3 + CloudFront hosts it better — no server runtime at all. |
| ECS/Fargate containers | Lambda | Fargate cannot scale to zero; Lambda can, and needs no application change. |
| Redis cache | none | The AI cache is `tr_ai` in PostgreSQL. Redis would be a standing charge for a cache the database already holds. |
| Airflow | EventBridge → Lambda | Runs for seconds, once a night. `dags/transferops_pipeline.py` still exists and is gated by `tests/orchestration_checks.py`. |
| Secrets Manager | SSM Parameter Store | $0 vs ~$2.80/month for rotation nothing here uses. |
