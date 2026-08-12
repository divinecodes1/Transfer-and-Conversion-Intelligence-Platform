/**
 * Transfer & Conversion Intelligence Platform :: ingestion and pipeline health.
 *
 * This screen is deliberately read-only, and the reason is worth stating rather
 * than hiding.
 *
 * The reference console this was modelled on has a CSV upload form. This
 * platform's analytics API opens its session **read-only**, so a write is
 * refused by PostgreSQL rather than by convention — a property `api_checks`
 * asserts, and the one the assistant inherits instead of having to be trusted
 * with. An upload form here would require relaxing exactly that.
 *
 * So ingestion stays where its quality tiers and quarantine already live —
 * `etl/ingest.py`, run by the operator or the orchestrator — and this screen
 * does the part a console is actually better at: showing whether the last load
 * worked, how long it took, and how many gates it cleared.
 */
import { queryOptions, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Copy, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { get } from "@/lib/api";
import { fmtNumber } from "@/lib/marts";

type PipelineRun = {
  run_id: number;
  engine: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  rows_loaded: number | null;
  dq_passed: number | null;
  dq_failed: number | null;
  status: string;
};

const runsQuery = () =>
  queryOptions({
    queryKey: ["pipeline-runs"],
    queryFn: ({ signal }) => get<{ runs: PipelineRun[] }>("/pipeline/runs", undefined, signal),
    retry: false,
  });

const LAYERS = [
  {
    layer: "tr_raw",
    role: "Source-faithful landing",
    note: "Every column kept as text, so an unparseable date survives ingestion intact and “did the source send it wrong, or did we transform it wrong?” is answerable by diffing two layers.",
  },
  {
    layer: "tr_stg",
    role: "Typed, standardised, deduplicated",
    note: "Safe casts and domain checks. Rows with no safe interpretation are quarantined here rather than reaching the canonical model.",
  },
  {
    layer: "tr_core",
    role: "Canonical model with full history",
    note: "The immutable baseline plus every replan, and the forecast as known on each date. Without this, original-vs-latest and forecast accuracy are not computable.",
  },
  {
    layer: "tr_metric",
    role: "One definition per KPI",
    note: "The calculation layer. Every dashboard, export and assistant answer reads from here.",
  },
];

const TIERS = [
  {
    tier: "REJECT",
    variant: "bad" as const,
    meaning:
      "No safe interpretation — an unparseable date, a status outside the approved domain, a missing mandatory field. These rows never reach CORE.",
  },
  {
    tier: "WARN",
    variant: "warn" as const,
    meaning:
      "A problem with the delivery that staging already resolves deterministically — a duplicate the pipeline handled. Dropping a project over one of these would lose good data.",
  },
];

export function IngestionScreen() {
  const query = useQuery(runsQuery());
  const runs = query.data?.runs ?? [];
  const last = runs[0];
  const lastSuccess = runs.find((run) => run.status === "SUCCESS");

  const command =
    "python etl/ingest.py --engine postgres --dsn $TRANSFEROPS_DSN   # add --corrupt to watch the quarantine work";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Ingestion"
        description="Pipeline health, and how data reaches the metric layer."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          label="Last load"
          value={last?.status ?? "—"}
          hint={last ? new Date(last.started_at).toLocaleString() : "No runs recorded"}
          tone={last?.status === "SUCCESS" ? "ok" : last ? "bad" : "neutral"}
          loading={query.isLoading}
        />
        <KpiTile
          label="Rows loaded"
          value={fmtNumber(last?.rows_loaded)}
          loading={query.isLoading}
        />
        <KpiTile
          label="Gates cleared"
          value={`${last?.dq_passed ?? "—"} / ${(last?.dq_passed ?? 0) + (last?.dq_failed ?? 0)}`}
          tone={last?.dq_failed ? "bad" : "ok"}
          loading={query.isLoading}
        />
        <KpiTile
          label="Last successful load"
          value={lastSuccess ? new Date(lastSuccess.started_at).toLocaleDateString() : "—"}
          hint={
            lastSuccess?.duration_ms ? `${(lastSuccess.duration_ms / 1000).toFixed(1)} s` : undefined
          }
          loading={query.isLoading}
        />
      </div>

      <Panel title="Load history" description="From the one table a warehouse rebuild does not erase.">
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={runs.length === 0}
          emptyMessage="No load has been recorded against this warehouse yet."
          onRetry={() => void query.refetch()}
          rows={5}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Engine</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Rows</TableHead>
                <TableHead>Gates passed</TableHead>
                <TableHead>Gates failed</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.run_id}>
                  <TableCell className="num text-xs">
                    {new Date(run.started_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="num text-xs">{run.engine}</TableCell>
                  <TableCell>
                    <Badge dot variant={run.status === "SUCCESS" ? "ok" : "bad"}>
                      {run.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="num">{fmtNumber(run.rows_loaded)}</TableCell>
                  <TableCell className="num">{run.dq_passed ?? "—"}</TableCell>
                  <TableCell className={run.dq_failed ? "num text-bad" : "num"}>
                    {run.dq_failed ?? "—"}
                  </TableCell>
                  <TableCell className="num text-xs">
                    {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)} s` : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="size-4" />
              The layered path
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Layer</TableHead>
                  <TableHead>Role</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {LAYERS.map((entry) => (
                  <TableRow key={entry.layer}>
                    <TableCell className="num align-top text-xs font-medium">
                      {entry.layer}
                    </TableCell>
                    <TableCell>
                      <div className="text-xs font-medium">{entry.role}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{entry.note}</div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-4" />
              Quarantine severity
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Severity is what makes a quality gate useful rather than annoying. Treating every
              finding as fatal is how teams end up disabling their own gates.
            </p>
          </CardHeader>
          <CardContent className="space-y-3">
            {TIERS.map((tier) => (
              <div key={tier.tier} className="rounded-md border border-border p-3">
                <Badge dot variant={tier.variant}>
                  {tier.tier}
                </Badge>
                <p className="mt-1.5 text-xs text-muted-foreground">{tier.meaning}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-4 text-ok" />
            Running a load
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Ingestion is a pipeline command, not a console action. The analytics API this screen
            reads from opens its session read-only, so it cannot write — and that property is what
            lets the assistant inherit a read-only posture instead of being trusted with one.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-2 rounded-md border border-border bg-muted/50 p-3">
            <code className="num flex-1 text-xs">{command}</code>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void navigator.clipboard.writeText(command)}
            >
              <Copy />
              Copy
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            The quality gates run <em>after</em> the load and raise rather than warn: a refresh
            that silently changes a KPI is worse than one that failed.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
