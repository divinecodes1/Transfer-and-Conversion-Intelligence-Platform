# Architecture

Two diagrams, for two audiences. Showing the wrong one is how a good design
conversation turns into a tooling conversation.

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
