# Three-Week Pilot — and the "how would you start?" answer

## The spoken answer

> "I wouldn't start by rebuilding the platform, and I wouldn't start with an LLM.
>
> I'd take one reporting flow — cycle time and original-versus-latest schedule,
> because they're already central to your reporting — and trace it end to end:
> source data, through the existing calculations, to the dashboard. I'd document
> what the current definition actually is and reproduce a handful of real
> projects by hand, because until the numbers reconcile nothing else is safe to
> change.
>
> Then I'd build the clean model underneath it — project, milestone and schedule
> revision history — because preserving the original baseline is what makes
> original-versus-latest answerable at all. The KPI calculation moves into one
> governed SQL layer, and the dashboard consumes that instead of computing its own.
>
> Once it matches the existing report, that flow becomes the reference for
> migrating the rest. The AI part comes only after the metrics are trusted: it
> queries those governed definitions, states which metric and filters it used and
> how fresh the data is, stays read-only, and inherits the same permissions as
> the reporting platform."

The load-bearing word is **one**. Everything else follows from picking a single
flow and finishing it.

---

## Week 1 — understand, don't build

**Objective:** understand one reporting chain end to end. The output is
understanding, not code volume.

- Sit with the business owner and confirm the actual question being asked.
- Sit with the technical colleagues who maintain the current implementation.
- Identify the exact source fields behind the numbers.
- Document how baseline and latest schedules are represented **today** — and
  specifically whether history is retained or overwritten. This single answer
  determines how much of the rest is even possible.
- Reproduce 5–10 real projects by hand.
- First data-quality read: nulls, duplicates, date ordering, orphans.

**Deliverables:** current-state flow diagram · source-table inventory ·
cycle-time and schedule-deviation definitions as they exist now · 5–10 golden
projects · initial DQ report.

**Questions that must get answered:** What defines start and completion? When is
a baseline frozen, and can it be re-baselined? Is every schedule change
preserved, or only the latest state? How are cancelled projects handled? What
counts as an approved schedule change versus an execution delay?

> These matter more than any tooling decision, because the definitions determine
> whether the metrics mean anything.

---

## Week 2 — build the governed metric

Build the calculation layer for that one flow: baseline schedule, latest
schedule, cycle time, schedule deviation — as governed views, registered with
owner, grain, population and version.

```
source → clean model → canonical KPI view → automated tests
```

Validate against the golden projects from week 1. Then one minimal dashboard:
cycle-time trend, original-versus-latest deviation, fiscal-year distribution,
project drill-down.

**Acceptance:** the golden projects reconcile, and the dashboard computes nothing
of its own.

---

## Week 3 — validate, then make it explain itself

Run legacy and pilot side by side. For every discrepancy, classify before fixing:

| Classification | What it means |
| --- | --- |
| Bug in the new implementation | Fix it |
| Bug in the legacy implementation | Raise it — this is a finding, not an inconvenience |
| Different refresh time | Not a discrepancy |
| Changed business definition | Needs the owner's sign-off, not an engineering decision |
| Known source-quality issue | Feeds the DQ backlog |

> Never delete or rewrite the old solution before its behaviour is understood.

Then a small read-only assistant over the validated metrics — roughly ten
approved questions ("What is median cycle time in FY26?", "Compare FY25 and
FY26", "Which projects are more than 30 days behind baseline?", "What does
schedule deviation mean?"). It calls approved metric functions; it does not
generate SQL.

**Final package:** architecture diagram · KPI dictionary · SQL repository ·
tests · dashboard prototype · validation report · assistant demo · a backlog for
the next three months.

---

## Beyond the pilot

| Stage | Responsibility |
| --- | --- |
| First months | Learn the domain, map existing reports, reproduce KPIs, write tests and documentation |
| Next | Own one data mart / KPI family, build migration pipelines, refactor dashboards, implement row-level security |
| Later | Semantic metadata, assistant tooling, evaluation suite |
| Long term | Own a reporting/AI capability and keep improving the architecture |

Two tracks run in parallel throughout, because urgent reporting requests do not
pause for a renovation:

```
TRACK A — RUN     urgent reports, fixes, new filters, user support
TRACK B — CHANGE  data architecture, metric standardisation, migration, AI
early ~50/50, shifting toward CHANGE as the governed layer takes load
```

**Migration rule for every legacy component:** discover → document current result
→ define the canonical rule → rebuild → validate against golden → rebuild
dashboard → dual-run → business acceptance → retire the old one.

---

## Positioning

Say:

> "I built an end-to-end reference implementation inspired by the requirements we
> discussed."

Not:

> "I rebuilt the platform in two days."

The real platform has years of domain knowledge, production integration,
governance, security review, real source systems and real entitlements behind it.
A prototype proves architecture, engineering judgement and initiative — which is
the honest claim, and the stronger one.
