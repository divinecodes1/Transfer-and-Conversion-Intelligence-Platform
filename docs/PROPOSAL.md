# Transfer Performance Reporting Platform — Modernisation Proposal

*Parth Goswami · working prototype: [Transfer & Conversion Intelligence Platform](../README.md)*

> This is an open-stack replica built on synthetic data. It demonstrates an
> architectural pattern; it does not reproduce or represent Infineon's internal
> systems.

---

## Problem

The platform tracks transfer-project performance successfully today. What has
accumulated alongside it is the cost of years of incremental additions: KPI logic
distributed across reports, workbooks and ad-hoc calculations, so two dashboards
can answer the same question differently and neither is wrong on its own terms.
Users also need reporting to become self-explaining — today it takes knowing which
filters to set, and that knowledge does not transfer to the next person.

## Goal

A governed reporting architecture that gives consistent project-performance
metrics, preserves historical schedules and forecasts, serves BI efficiently, and
creates a safe foundation for natural-language analytics.

## Proposed flow

```
Sources → RAW / STAGING → Canonical CORE (+ revisions + snapshots)
        → Governed METRIC layer → Reporting MARTS → BI → Read-only AI assistant
                          ▲
              Governance: metric catalogue · entitlements · audit
```

## Initial metrics

Cycle Time · Schedule Deviation · Completion Variance · Forecast Error (by
horizon) · Throughput · On-Time Rate · Stage Cycle Time · Cycle-Time Distribution

## Design principles

1. **Preserve history explicitly.** An immutable baseline plus every replan and a
   dated forecast snapshot. Overwrite `planned_finish` and "original vs latest"
   becomes permanently unanswerable.
2. **One governed definition per KPI**, registered with owner, grain, population
   and version — and *tested* against its implementation, not just documented.
3. **BI visualises; it never redefines.** No dashboard recomputes a metric.
4. **Security below the visualisation layer.** A workbook filter is not a boundary.
5. **LLMs handle language; deterministic systems calculate.** The assistant reads
   the metric catalogue and calls governed tools. It never writes SQL, and every
   narrative it writes is grounded in numbers fetched under the reader's own
   entitlements — so a model cannot describe a portfolio its reader may not see.
6. **Reconcile before you retire.** No legacy metric is switched off until the new
   one reproduces its numbers on an agreed golden set.

## First pilot

Rebuild one end-to-end flow — cycle time and schedule performance — from source
data through a governed SQL layer to a dashboard. Reconcile it against the
existing report, document it, then expose the validated metric to a small
read-only assistant. Use that flow as the reference for migrating the rest.

## What the prototype already demonstrates

| | |
| --- | --- |
| Governed metric layer | 9 metrics, each registered *and* verified against its implementation |
| History preserved | 904 schedule revisions, 3,694 dated forecast snapshots over 260 projects |
| Before/after | An accreted legacy query reproduces the same headline numbers — and still contradicts itself by 2.5 points on on-time rate |
| Forecast quality | Median error 2 → 6 → 11 → 30 days as the horizon lengthens; measuring only the latest forecast hides this entirely |
| Bottleneck | Tapeout → Qualification Lots is the slowest stage at 62 days median |
| Access control | Two managers, same question, different answers — enforced in the database, not the dashboard |
| Assistant | 26/26 evaluation cases; 100% provenance; abstains on ambiguity; zero security violations |
| AI, fenced | Briefings, risk estimates and drafts written *from* governed numbers under the reader's own entitlements — optional, and the platform runs identically with it switched off |
| Verification | 207 automated assertions across eighteen suites |

## What I would not do

Start by adding another dashboard or connecting an LLM to the warehouse. Both are
faster to show and neither addresses the actual problem, which is that the same
question does not yet have one answer.

## Honest scope

A production platform of this shape is roughly a **20–34 FTE-month** programme.
This prototype is a reference implementation of the pattern, built to argue a
design — not a claim that the platform can be rebuilt quickly. The realistic
contribution is owning one KPI family end-to-end, proving it against the current
reports, and widening from there.
