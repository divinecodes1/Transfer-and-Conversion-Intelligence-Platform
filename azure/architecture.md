# Azure Architecture — Student Tier

> Production-quality architectural thinking without production-level spending.

Nine resources, one region, one resource group. Every one of them either scales
to zero, sits inside a free monthly grant, or is the smallest SKU its service
offers.

---

## The deployed shape

```text
                            INTERNET
                                │
                                ▼
              ┌─────────────────────────────────┐
              │ Azure Static Web Apps   (Free)  │
              │ the React console, static files │
              └────────────────┬────────────────┘
                               │ HTTPS + bearer token
              ┌────────────────┼────────────────┐
              ▼                                 ▼
   ┌────────────────────┐            ┌────────────────────┐
   │ Container App: api │            │ Container App: auth│
   │ FastAPI            │            │ Keycloak           │
   │ Consumption, min=0 │◀──JWKS─────│ Consumption, min=0 │
   └─────────┬──────────┘            └─────────┬──────────┘
             │                                 │
             ├──────────────┬──────────────┐   │
             ▼              ▼              ▼   ▼
      ┌────────────┐  ┌──────────┐  ┌──────────────────────┐
      │ Blob       │  │ Key Vault│  │ PostgreSQL Flexible  │
      │ Storage    │  │          │  │ B1ms, 32 GB          │
      │            │  │          │  │  ├── transferops     │
      │            │  │          │  │  └── keycloak        │
      └────────────┘  └──────────┘  └──────────────────────┘
             ▲              ▲
             └──────┬───────┘
                    │ managed identity, no keys
        ┌───────────┴────────────┐
        │ Container Apps Job     │
        │ cron 02:00, on demand  │
        └────────────────────────┘

               Log Analytics + Application Insights
                  (capped at 0.1 GB/day ingestion)
```

There is no Kubernetes, no Front Door, no Application Gateway, no Firewall, no
Redis, no private endpoint, no dedicated vector database and no Airflow cluster.
Each is a real production component and each is a standing charge; see
[migration-to-enterprise.md](migration-to-enterprise.md).

---

## Why each choice

### Static Web Apps for the console

The console is a **Vite SPA** — static files with no server runtime. It needs no
SSR, no Node process and no scaling behaviour, so the Free tier is not a
compromise but an exact fit: managed TLS, a global CDN and 100 GB/month of
bandwidth for nothing.

It also decouples the two failure modes usefully. The page paints instantly even
while the API is cold-starting, so a scaled-to-zero backend looks like a loading
state rather than an outage.

> The master plan specifies Next.js. This repository's console is Vite + React +
> TanStack Router. Nothing in the Azure design depends on the difference —
> Static Web Apps hosts either — but no Next.js server features (ISR, route
> handlers, middleware) are available, because there is no Next.js server. Every
> screen in this console is client-rendered against the governed API, so none
> were needed.

### Container Apps for the API

Consumption workload profile, `min_replicas = 0`. An idle demo bills nothing;
the monthly free grant (180,000 vCPU-seconds, 360,000 GiB-seconds, 2M requests)
covers demonstration traffic outright.

The cost is a few seconds of cold start on the first request after idle. For a
portfolio piece nobody is hitting at 3am, that is the correct side of the trade.

AKS was rejected outright: a control plane, a node pool that cannot scale to
zero, and a networking bill, to run one Python service. The repository still
carries `kubernetes/transferops.yaml` and `tests/k8s_checks.py` — the manifests
are the *enterprise* story, proven to parse, probe and lock down, without being
what the prototype pays for.

### Keycloak for identity

Keycloak runs as its own Container App with its own database on the shared
PostgreSQL server, at `min_replicas = 0` like everything else.

This is the one component where scale-to-zero has a visible cost: a cold JVM
takes **40–60 seconds** to serve the first sign-in. The alternative is worse.
Held warm at 0.5 vCPU / 1 GiB, Keycloak consumes roughly 1.3M vCPU-seconds a
month against a 180k free grant — about **30–35 USD/month, a third of the entire
student credit**, spent almost entirely on idle time.

What Keycloak buys, and why it is not replaced by a cloud identity service: the
branded realm, the login and email themes, self-registration, email verification
and password recovery are part of what the platform demonstrates. A tenant login
page would remove all of it.

`api/auth.py` needs no code change to run in Azure. It builds the issuer and the
JWKS URL from `KEYCLOAK_URL` and `KEYCLOAK_REALM`; Terraform points those at the
Keycloak Container App's HTTPS hostname and verification proceeds exactly as it
does locally.

### One PostgreSQL server, two databases

`transferops` (the warehouse) and `keycloak` (identity state) share one Flexible
Server. Flexible Server bills per **server**, so co-tenanting costs nothing while
a dedicated instance would double the largest standing charge in the stack. The
isolation that matters — separate databases, separate credentials, no shared
tables — is preserved.

B1ms with 32 GB is deliberate. The warehouse is ~260 projects with full schedule
history: a few hundred thousand rows, working set in memory. The bottleneck in
this platform has never been the database.

No HA, no geo-redundant backup, no read replica. Each doubles a cost to protect
a synthetic dataset that rebuilds from `sql/` in about a minute.

### Container Apps Job for pipelines

The nightly refresh runs on a cron trigger, executes, and stops. No idle cost and
no cluster to keep alive — which is why Airflow is deferred to the enterprise
architecture rather than deployed here. The repository still carries
`dags/transferops_pipeline.py` and `tests/orchestration_checks.py`, so the
Airflow path is designed and gated without being provisioned.

### Managed identity everywhere it fits

Blob Storage and Key Vault are reached by a user-assigned managed identity. The
storage account has **shared key access disabled outright**, so the credential
that would otherwise need rotating does not exist.

The identity is user-assigned rather than system-assigned so one principal serves
the API, the job and any future worker. A system-assigned identity dies with its
resource, and every role assignment has to be re-granted on replacement.

### Observability with a hard cap

Log Analytics ingestion is capped at **0.1 GB/day** — a real cap, not an alert.
Ingestion stops for the day when it is hit. Losing an afternoon of demo logs is
an acceptable failure mode; a retry loop quietly eating the credit overnight is
not.

---

## What the application already brought

A large part of the "AI-assisted platform" in the master plan was already built
and is not re-implemented here:

| Master plan | Where it already lives |
|---|---|
| §45 KPI semantic layer | `tr_gov.metric_definition` + `sql/03_metric_views.sql`, with a gate proving catalogue and implementation agree |
| §34 AI governance | the `ai/` fence — closed tool list, caller scope overriding model arguments, hallucinated ids dropped |
| §19 Ask Your Data | `agent/` — catalogue-bound resolution with abstention and injection tests |
| §17 Historical similarity **without an LLM** | `tr_metric.v_transfer_similarity` — deterministic, four published weights |
| §18 Predictive risk **without an LLM** | `ai/risk.py`, fenced into `tr_ai` so a model's opinion can never acquire a metric code |
| §13 Readiness engine | `sql/13_readiness_network.sql`, weights stored as data |
| §27 Data quality | `etl/dq_checks.py` + nine loader gates |
| §36 Audit | `agent/audit.py` via a least-privilege auditor role |

The Azure layer hosts this platform. It does not reinvent it.

---

## Deliberate divergences from the master plan

| Plan says | Deployed as | Why |
|---|---|---|
| Next.js | Vite + React SPA | What the repo is. Static Web Apps hosts it better — no server runtime at all. |
| Microsoft Entra ID | Keycloak | Explicit project decision. The realm and its themes are part of the demonstration. |
| SQLAlchemy + Alembic | Raw SQL + `etl/run.py` | The numbered `sql/` files *are* the migration system, and the golden gate asserts against them. |
| `/api/v1/*` routes | `/mart/*`, `/metrics/*`, `/ai/*` | Existing contract, asserted by `tests/api_checks.py`. |
| Redis cache | none | The AI cache is `tr_ai` in PostgreSQL. A Redis instance is a standing charge for a cache the database already holds. |
| ACR | GitHub Container Registry | ACR Basic is a fixed ~5 USD/month — 5% of the credit, monthly, for what GHCR gives free. `use_acr = true` restores it. |
