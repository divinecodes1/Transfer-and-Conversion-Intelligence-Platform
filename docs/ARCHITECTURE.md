# Architecture

Two diagrams, for two audiences. Showing the wrong one is how a good design
conversation turns into a tooling conversation.

Those two come first because they are the ones worth arguing about. The rest of
this file is the same system seen from four other angles — the model it stores,
the machines it runs on, the path a single request takes, and the two pipelines
that keep it current. Each exists because someone eventually asks a question the
logical diagram cannot answer:

| View | The question it answers |
| --- | --- |
| [Business](#for-the-business-conversation) · [Engineering](#for-the-engineering-conversation) | "What are the layers, and why are they separate?" |
| [The core model](#the-core-model) | "Where does the history actually live?" |
| [Where it runs](#where-it-runs) | "What does this cost, and what is exposed?" |
| [The request path](#the-request-path) | "What happens between a click and a row?" |
| [Identity to row](#identity-to-row) | "Where exactly is a permission enforced?" |
| [The two pipelines](#the-two-pipelines) | "What runs on a schedule, and what happens when it fails?" |
| [How code ships](#how-code-ships) | "How does a commit become the running system?" |

---

## For the business conversation

Five boxes. The only claim being made is that the layers are *separate*, and that
each one has a single job.

```mermaid
flowchart TD
    S["Transfer project sources<br/><i>projects · schedules · milestones · forecasts</i>"]
    D["DATA FOUNDATION<br/><b>clean, and historical</b><br/><i>every replan and forecast kept</i>"]
    K["CALCULATION<br/><b>one definition per metric</b><br/><i>cycle time defined once</i>"]
    R["REPORTING<br/><b>dashboards consume, never redefine</b>"]
    A["SELF-EXPLAINING ASSISTANT<br/><b>answers with its own definitions attached</b>"]

    S --> D --> K --> R
    K --> A
    R --> A

    style D fill:#e3f2fd,stroke:#1565c0
    style K fill:#e8f5e9,stroke:#2e7d32
    style R fill:#fff3e0,stroke:#ef6c00
    style A fill:#f3e5f5,stroke:#6a1b9a
```

The sentence that goes with it:

> *"I separate source data, business calculation and presentation, so a metric
> like cycle time is defined once and reused everywhere. Then the AI sits on
> trusted metrics instead of raw tables."*

---

## For the engineering conversation

```mermaid
flowchart TB
    SRC["Transfer project sources<br/><i>project master · schedules · milestones · forecasts</i>"]

    subgraph ING ["INGESTION - three data-quality tiers"]
        direction LR
        RAW["<b>tr_raw</b><br/>untyped, source-faithful<br/><i>what did they send?</i>"]
        Q["quarantine<br/><i>REJECT held back<br/>WARN resolved</i>"]
        STG["<b>tr_stg</b><br/>typed · standardised · deduped<br/><i>what does it mean?</i>"]
        RAW --> Q
        RAW --> STG
    end

    subgraph COR ["CANONICAL MODEL - history preserved explicitly"]
        direction LR
        DP["dim_project"]
        FR["fact_schedule_revision<br/><i>immutable baseline + every replan</i>"]
        FS["fact_project_snapshot<br/><i>forecast as known on each date</i>"]
        FM["fact_milestone_event"]
    end

    MET["<b>tr_metric</b> - CALCULATION LAYER<br/>one governed definition per KPI"]
    GOV[("<b>tr_gov</b><br/>metric catalogue<br/>entitlements · audit · ETL runs")]
    MART["<b>tr_mart</b> - reporting marts"]
    API["Analytics API<br/><i>read-only · provenance envelope</i>"]
    WEB["Product console<br/><i>React · twelve screens</i>"]
    BI["Reference dashboard<br/><i>management · technical/PMO</i>"]
    AI["Assistant<br/><i>catalogue-bound · read-only</i>"]
    MODEL["AI layer<br/><i>optional · phrases, never computes</i>"]
    TRAI[("<b>tr_ai</b><br/>narratives · risk estimates<br/>refresh log — not metrics")]
    OBS["Prometheus / Grafana<br/><i>pipeline · API · adoption</i>"]

    SRC --> ING
    STG --> COR
    COR --> MET
    MET --> MART
    MART --> API
    MET --> API
    API --> WEB
    API --> BI
    API --> AI
    API --> MODEL
    MODEL -.writes cache.-> TRAI
    TRAI -.read via API, scoped.-> WEB
    GOV -.governs.-> MET
    GOV -.resolves identity.-> API
    GOV -.defines vocabulary.-> AI
    GOV -.generates the prompts' metric rules.-> MODEL
    API -.telemetry.-> OBS
    AI -.telemetry + audit.-> OBS

    style RAW fill:#eceff1,stroke:#546e7a
    style STG fill:#eceff1,stroke:#546e7a
    style Q fill:#ffebee,stroke:#c62828
    style MET fill:#e8f5e9,stroke:#2e7d32
    style GOV fill:#fffde7,stroke:#f9a825
    style MART fill:#fff3e0,stroke:#ef6c00
    style API fill:#e3f2fd,stroke:#1565c0
    style WEB fill:#e3f2fd,stroke:#1565c0
    style AI fill:#f3e5f5,stroke:#6a1b9a
    style MODEL fill:#f3e5f5,stroke:#6a1b9a
    style TRAI fill:#f3e5f5,stroke:#6a1b9a
```

The arrow that is *missing* is the load-bearing one: nothing runs from `MODEL`
down to the warehouse. The AI layer holds no database handle, so it reaches every
figure through the same governed API the console calls, under the caller's
identity — and it writes its cache through a role that can write `tr_ai` and read
nothing.

### Why each boundary exists

| Boundary | The question it makes answerable |
| --- | --- |
| `tr_raw` / `tr_stg` | "Did the source send it wrong, or did we transform it wrong?" — answered by diffing two layers rather than by arguing |
| `fact_schedule_revision` | "How far has the plan moved from what we committed to?" — impossible once `planned_finish` is overwritten |
| `fact_project_snapshot` | "What did we believe three months ago?" — the only way forecast accuracy is measurable at controlled horizons |
| `tr_metric` | "Whose number is right?" — there is only one, and it is version-controlled |
| `tr_gov` | "What does this metric mean, who owns it, and who may see it?" |
| Analytics API | "Can BI and the assistant drift apart?" — no; they consume one contract |
| `tr_ai` | "Is this number governed, or is it a model's opinion?" — the schema boundary answers it, and no row here is registered as a metric |

### Enforcement

Entitlements are a **PostgreSQL row-level policy** on `tr_core.dim_project`, which
every metric view reaches through. Three things must hold together, and missing
any one leaves the policy installed but inert:

1. `FORCE ROW LEVEL SECURITY` — or the table owner bypasses its own policy.
2. A **non-superuser** connection — superusers bypass RLS unconditionally.
3. `security_invoker` on every view — or a view owned by the schema owner
   evaluates the policy as *its owner* and returns everything.

Fail-closed: an unset scope selects zero rows.

### The assistant's trust boundary

```mermaid
flowchart LR
    Q["question<br/><i>untrusted</i>"] --> R["resolver<br/><i>catalogue vocabulary</i>"]
    R --> M["MetricQuery<br/><b>validated, inspectable</b>"]
    M --> E["executor<br/><b>trusted code</b>"]
    E --> API["read-only API"]
    API --> DB[("read-only DB session<br/>+ row-level policy")]
    M -.->|ambiguous| C["clarify — offer the<br/>registered candidates"]
    M -.->|injection or write| X["refuse"]

    style Q fill:#ffebee,stroke:#c62828
    style M fill:#e8f5e9,stroke:#2e7d32
    style E fill:#e3f2fd,stroke:#1565c0
    style X fill:#ffebee,stroke:#c62828
```

Every authority sits *below* the language layer. Claiming to be an admin in a
question buys nothing, because scope is resolved from identity before the
executor runs and enforced by the database.

### The model's trust boundary

The same shape, one level up, for the optional AI layer. The model chooses
*which* governed endpoint to call; it never chooses what a metric means.

```mermaid
flowchart LR
    U["question / screen scope<br/><i>untrusted</i>"] --> M["model<br/><i>picks a tool + filters</i>"]
    M --> T["closed tool list<br/><b>six governed endpoints</b>"]
    T --> X["executor - our code<br/><i>caller's scope merged in</i>"]
    X --> API["governed API<br/><i>provenance envelope attached</i>"]
    API --> SNAP["snapshot<br/><b>the only numbers the model sees</b>"]
    SNAP --> N["narrative / risk estimate<br/><i>stamped with its vintage</i>"]
    N --> C[("tr_ai<br/>write-only role")]
    M -.->|names a path| R["not possible -<br/>no path reaches a callable"]

    style U fill:#ffebee,stroke:#c62828
    style T fill:#e8f5e9,stroke:#2e7d32
    style X fill:#e3f2fd,stroke:#1565c0
    style SNAP fill:#e8f5e9,stroke:#2e7d32
    style R fill:#ffebee,stroke:#c62828
```

Three consequences worth stating, because they are the whole reason a generated
paragraph is safe to print beside a governed number:

1. **The snapshot is fetched under the caller's identity**, so the row-level
   policy filters it before it is serialised into a prompt. A narrative cannot
   name a portfolio its reader may not see.
2. **Filters are merged, never replaced.** The screen's scope is applied on top
   of whatever the model asked for, so a question cannot widen a view.
3. **Output is stamped and expiring.** It carries the `data_as_of` it was written
   from and stops being served when a new load lands — because a briefing about
   last week's warehouse beside this week's chart is worse than no briefing.

---

## The core model

The logical diagram says "history preserved explicitly". This is where that claim
is actually cashed: a conformed star whose three fact tables exist so that the
past cannot be overwritten.

```mermaid
erDiagram
    dim_project ||--o{ fact_schedule_revision : "every replan"
    dim_project ||--o{ fact_project_snapshot : "what we believed, per date"
    dim_project ||--o{ fact_milestone_event : "gate dates"
    dim_project ||--o{ fact_readiness_assessment : "scored dimensions"
    dim_project }o--|| dim_product_line : portfolio
    dim_project }o--|| dim_application : segment
    fact_milestone_event }o--|| dim_milestone : "which gate"
    fact_project_snapshot }o--|| dim_fiscal_date : "as of"
    fact_readiness_assessment }o--|| dim_readiness_dimension : "which axis"

    dim_project {
        int project_key PK
        string project_id UK
        string transfer_type
        string complexity_class
        string source_site
        string target_site
        date baseline_finish "frozen, never updated"
        date actual_finish
    }
    fact_schedule_revision {
        int project_key FK
        int revision_no
        date planned_finish "as at this revision"
        date revised_on
    }
    fact_project_snapshot {
        int project_key FK
        date snapshot_date
        date forecast_finish "as known on snapshot_date"
    }
```

Two columns carry the whole design.

`dim_project.baseline_finish` is written once and never updated;
`fact_schedule_revision` receives a new row per replan instead. The usual shape —
a single `planned_finish` updated in place — is cheaper, smaller, and makes "how
far has this moved from what we committed to?" permanently unanswerable, because
the number it moved *from* has been overwritten by the movement.

`fact_project_snapshot` is the same argument in the forecast dimension: one row
per project per date, holding what the forecast said *on that date*. Without it,
forecast accuracy can only be measured against whichever forecast happened to be
current when someone asked, which is not a measurement. With it, error is
measurable at a controlled horizon — the "11 days inside 30" versus "52 days at
90+" figures on the Forecast screen are a `GROUP BY` over this table, not an
estimate.

Row-level security attaches to `dim_project`, and every metric view reaches the
facts through it. That is why one policy on one table governs the whole
warehouse.

---

## Where it runs

Everything below fits inside the AWS Free Plan envelope, which is a design
constraint rather than an afterthought: it is why the API is a Lambda that scales
to zero rather than a service that idles, and why there is no NAT Gateway.

```mermaid
flowchart TB
    USER["Browser"]

    subgraph EDGE ["Edge"]
        CFA["CloudFront<br/><i>console</i>"]
        CFK["CloudFront<br/><i>Keycloak</i>"]
        AGW["API Gateway HTTP API<br/><i>29s integration ceiling</i>"]
    end

    subgraph VPC ["VPC - two availability zones"]
        subgraph PUB ["public subnets x2"]
            KC["EC2 t3.micro<br/><b>Keycloak</b> + <b>NAT instance</b><br/><i>source_dest_check off</i>"]
        end
        subgraph PRIV ["private subnets x2 - no inbound from the internet"]
            LAPI["Lambda <b>api</b><br/><i>uvicorn via Lambda Web Adapter</i>"]
            LREF["Lambda <b>refresh</b><br/><i>same image - 900s - event driven</i>"]
            RDS[("RDS PostgreSQL 16<br/>db.t4g.micro - private<br/><i>row-level security</i>")]
        end
    end

    LASST["Lambda <b>assistant</b><br/><i>outside the VPC by design</i>"]
    S3W["S3 - console bundle"]
    S3D["S3 - documents"]
    SSM[["SSM Parameter Store<br/><i>SecureString secrets</i>"]]
    ECR[["ECR - one image, three functions"]]
    EVB["EventBridge<br/><i>02:00 UTC daily</i>"]

    USER --> CFA --> S3W
    USER --> CFK --> KC
    USER --> AGW
    AGW --> LAPI
    AGW --> LASST
    LASST -. "HTTPS, forwarding the user's token" .-> AGW
    LAPI --> RDS
    LREF --> RDS
    LAPI --> S3D
    LAPI -. "verify JWT via JWKS" .-> KC
    LAPI -. "internet egress via NAT" .-> KC
    EVB --> LREF
    ECR -.-> LAPI
    ECR -.-> LREF
    ECR -.-> LASST
    SSM -.-> LAPI

    style RDS fill:#e3f2fd,stroke:#1565c0
    style KC fill:#fffde7,stroke:#f9a825
    style LAPI fill:#e8f5e9,stroke:#2e7d32
    style LREF fill:#e8f5e9,stroke:#2e7d32
    style LASST fill:#f3e5f5,stroke:#6a1b9a
```

Four choices there are load-bearing rather than incidental.

**One EC2 instance is both Keycloak and the NAT.** A NAT Gateway is roughly 32
USD a month and would be the largest single line on this deployment; a `t3.micro`
with `source_dest_check` disabled, and a private route pointed at it, does the
same job for traffic this size on a host that had to exist anyway. It is the
clearest case of the cost constraint shaping the topology.

**The API is a container image, not a handler.** The AWS Lambda Web Adapter runs
the same `uvicorn api.main:app` that runs locally, so `api/main.py` holds no
Mangum import and no handler signature, and `tests/api_checks.py` drives the same
ASGI app the deployment serves. A different entry point in production would mean
the tested contract and the served contract are not the same contract.

**The assistant sits outside the VPC on purpose.** It forwards the end user's
Keycloak token and reaches the API over HTTPS like any other caller, so it is
never given a warehouse credential and has no private path to RDS. Being outside
the VPC makes that structural rather than a matter of configuration discipline.

**Ingress is API Gateway, not a Function URL** — and not by preference. This
account refuses `lambda:InvokeFunctionUrl` for every caller, signed or anonymous,
while `lambda:InvokeFunction` succeeds, so no policy or signature routes around
it. The 29-second integration ceiling that comes with it is why the nightly
refresh does not run over HTTP.

---

## The request path

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant K as Keycloak
    participant G as API Gateway
    participant A as Lambda (api)
    participant D as PostgreSQL

    B->>K: OIDC login (PKCE)
    K-->>B: access token (held in memory, never localStorage)
    B->>G: GET /mart/kpis + Bearer
    G->>A: invoke
    A->>K: fetch JWKS (cached)
    A->>A: verify signature, issuer, audience, expiry
    A->>D: resolve roles and entitlements from tr_gov
    A->>D: set_config('transferops.portfolios', scope)
    A->>D: query tr_metric views
    D-->>A: only the rows the policy allows
    A-->>B: figures plus provenance envelope
```

Step 8 is the one that matters. The scope is set on the connection at checkout,
before any query runs, so no endpoint has to remember to filter — and because it
is re-set on every checkout, a pooled connection cannot inherit the previous
request's scope.

---

## Identity to row

Authentication and entitlement are different questions, answered in different
places. A token proves *who*; the database decides *what*.

```mermaid
flowchart LR
    T["Bearer token<br/><i>untrusted input</i>"] --> V["verify against JWKS<br/><i>signature - issuer<br/>audience - expiry</i>"]
    V -->|invalid| R1["401"]
    V -->|valid| U["username"]
    U --> E["tr_gov.user_role<br/>tr_gov.data_entitlement"]
    E -->|none| R2["403 - authenticated,<br/>entitled to nothing"]
    E -->|scope| S["set_config on the session"]
    S --> P["row-level policy<br/>on tr_core.dim_project"]
    P --> ROWS["the rows, and no others"]

    style T fill:#ffebee,stroke:#c62828
    style R1 fill:#ffebee,stroke:#c62828
    style R2 fill:#ffebee,stroke:#c62828
    style P fill:#e8f5e9,stroke:#2e7d32
```

Authenticating successfully while being entitled to nothing is a normal state,
and it answers 403 rather than rendering an empty dashboard — an empty dashboard
is indistinguishable from a quiet quarter.

The three conditions that keep the policy from being installed-but-inert
(`FORCE ROW LEVEL SECURITY`, a non-superuser connection, and `security_invoker`
on every view) are described under [Enforcement](#enforcement); each is asserted
by a test rather than trusted.

---

## The two pipelines

Two things run on a schedule, and they are sequenced rather than concurrent.

```mermaid
flowchart TB
    subgraph N1 ["1 - Warehouse load"]
        direction LR
        ETL["etl/run.py"] --> GATE{"data-quality<br/>gates"}
        GATE -->|fail| STOP["stop - the marts keep<br/>the last good vintage"]
        GATE -->|pass| PUB["publish the new vintage"]
    end

    subgraph N2 ["2 - AI refresh, 02:00 UTC"]
        direction LR
        EVB["EventBridge"] --> LWA["Lambda Web Adapter<br/><i>pass-through</i>"]
        LWA --> EP["POST /ai/refresh<br/><i>shared secret, constant-time</i>"]
        EP --> GEN["generate in-process<br/><i>governed routes only</i>"]
        GEN --> TRAI[("tr_ai<br/>narratives - risk - run log")]
    end

    PUB ==> EVB

    style GATE fill:#fffde7,stroke:#f9a825
    style STOP fill:#ffebee,stroke:#c62828
    style TRAI fill:#f3e5f5,stroke:#6a1b9a
```

**Ordering is the point.** A narrative generated against a half-loaded warehouse
is not stale, it is *wrong* — and it would carry the new vintage stamp while
describing the old data.

**The refresh never calls the API over the network.** EventBridge delivers a
payload, the web adapter's pass-through mode posts it to `/ai/refresh`, and the
endpoint verifies a shared secret in constant time before running generation
in-process through the same governed route functions an HTTP caller would reach.
No token crosses a wire and no service account holds standing access to governed
data. It also sidesteps the gateway's 29-second ceiling, which a job of this
length can never fit inside.

**Every run is recorded, failures included.** `tr_ai.run_log` is what the AI
Operations screen reads, and a scheduled job with no visible history is a job
that has been failing for a fortnight. Three properties keep that log honest:

- **Failure is per scope.** One scope that fails leaves the others warmed and
  lands in the log with its reason, rather than abandoning nine good briefings
  over the tenth.
- **The job stops itself.** One wall-clock deadline covers the whole run and is
  checked before every model call, so the job closes its own rows with a reason
  instead of being killed mid-write by the platform timeout — which leaves a row
  at `running` forever and reads on screen as a hang rather than a slow night.
- **A throttled provider is slow, not broken.** Calls retry with backoff,
  honouring `Retry-After`; when the day's token budget is genuinely spent, the
  scope is recorded as rate-limited and tomorrow's schedule is the retry.

---

## How code ships

```mermaid
flowchart LR
    PUSH["push to main"] --> GH["GitHub Actions<br/><i>OIDC - no stored AWS keys</i>"]
    GH --> T["gates: golden - governance<br/>marts - AI - console - security"]
    T -->|fail| X["no deploy"]
    T -->|pass| IMG["build and push image<br/><i>tagged with the commit SHA</i>"]
    IMG --> LOAD["schema and warehouse load<br/><i>via SSM, before the code rolls</i>"]
    LOAD --> ROLL["roll api - assistant - refresh"]
    ROLL --> SMOKE["smoke test /health"]

    style X fill:#ffebee,stroke:#c62828
    style GH fill:#e8f5e9,stroke:#2e7d32
```

**The database moves before the functions do.** Rolling the code first would put
code expecting a new column live against a database that does not have it, and
every request in that window fails. Loading first means the only overlap is old
code against a new schema, which additive changes tolerate.

**CI holds no AWS credentials.** It assumes a role through an IAM OIDC provider,
scoped to the three functions, two ECR repositories, the console bucket and one
CloudFront distribution — not `ec2:*`, not `iam:*`, and with no ability to change
the infrastructure it deploys onto. Terraform stays an operator action.

**Image tags are commit SHAs, and Terraform ignores them.** `ignore_changes =
[image_uri]` on each function is what stops the next `terraform apply` from
proposing a rollback to whatever tag the tfvars happens to name.
