/**
 * Transfer & Conversion Intelligence Platform :: AI automation history.
 *
 * The nightly refresh warms the narrative cache and re-scores in-flight projects
 * after the warehouse load. This screen is the reason that job is trustworthy: a
 * scheduled job with no visible run history is a job that has been failing for a
 * fortnight and nobody has noticed.
 *
 * Insight refreshes and risk refreshes are logged separately on purpose. "The AI
 * refresh failed" is not actionable; the two fail for different reasons and are
 * fixed in different places.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, SkipForward } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAiEnabled } from "@/components/ai";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { aiRunsQuery, type AiRun } from "@/lib/ai";

const STATUS = {
  success: { variant: "ok", icon: CheckCircle2, label: "Success" },
  failed: { variant: "bad", icon: AlertTriangle, label: "Failed" },
  running: { variant: "warn", icon: Clock, label: "Running" },
  skipped: { variant: "muted", icon: SkipForward, label: "Skipped" },
} as const;

function StatusBadge({ status }: { status: string }) {
  const entry = STATUS[status as keyof typeof STATUS] ?? STATUS.skipped;
  return (
    <Badge dot variant={entry.variant}>
      {entry.label}
    </Badge>
  );
}

function duration(ms: number | null) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function AutomationScreen() {
  const { enabled, status } = useAiEnabled();
  const query = useQuery(aiRunsQuery(100));
  const runs = query.data?.runs ?? [];

  const last = runs[0];
  const recentFailures = runs.slice(0, 20).filter((run: AiRun) => run.status === "failed").length;
  const lastSuccess = runs.find((run: AiRun) => run.status === "success");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Automation"
        description="Every scheduled and manual AI refresh, whether it worked, and what it cost."
      />

      {!enabled ? (
        <Card className="border-warn/25 bg-warn/5">
          <CardContent className="p-4 text-sm">
            <div className="font-medium text-warn">No model is configured</div>
            <p className="mt-1 text-muted-foreground">
              The refresh job has nothing to run. Dashboards, the metric catalogue and the
              deterministic assistant are unaffected. Set an AI credential to switch it on — see
              the environment reference in <span className="num">.env.example</span>.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          label="Last run"
          value={last ? STATUS[last.status as keyof typeof STATUS]?.label ?? last.status : "—"}
          hint={last ? new Date(last.started_at).toLocaleString() : "No runs recorded"}
          tone={last?.status === "failed" ? "bad" : last?.status === "success" ? "ok" : "neutral"}
          loading={query.isLoading}
        />
        <KpiTile
          label="Failures in last 20"
          value={String(recentFailures)}
          tone={recentFailures > 0 ? "bad" : "ok"}
          loading={query.isLoading}
        />
        <KpiTile
          label="Last success"
          value={lastSuccess ? new Date(lastSuccess.started_at).toLocaleDateString() : "—"}
          hint={lastSuccess?.detail ?? undefined}
          loading={query.isLoading}
        />
        <KpiTile
          label="Model"
          value={status?.ai?.model ?? "—"}
          hint={status?.ai?.provider ? `via ${status.ai.provider}` : undefined}
        />
      </div>

      {status?.cache?.degraded ? (
        <Card className="border-warn/25 bg-warn/5">
          <CardContent className="p-3 text-xs">
            <span className="font-medium text-warn">Cache degraded:</span>{" "}
            <span className="text-muted-foreground">{status.cache.degraded}</span> — narratives are
            still generated on demand, they are simply not being stored.
          </CardContent>
        </Card>
      ) : null}

      <Panel
        title="Run history"
        description="Newest first. Each row is one job, not one nightly window."
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={runs.length === 0}
          emptyMessage="No refresh has run yet. Trigger one with `make ai-refresh`, or wait for the scheduled window."
          onRetry={() => void query.refetch()}
          rows={6}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Job</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Items</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run: AiRun) => (
                <TableRow key={run.run_id}>
                  <TableCell className="num text-xs">
                    {new Date(run.started_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="num text-xs">{run.job}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{run.trigger}</TableCell>
                  <TableCell>
                    <StatusBadge status={run.status} />
                  </TableCell>
                  <TableCell className="num">{run.item_count}</TableCell>
                  <TableCell className="num text-xs">{duration(run.duration_ms)}</TableCell>
                  <TableCell className="max-w-80 text-xs text-muted-foreground">
                    {run.error_message ? (
                      <span className="text-bad">{run.error_message}</span>
                    ) : (
                      run.detail
                    )}
                    {run.scopes?.length ? (
                      <div className="mt-0.5 num text-[10px] opacity-70">
                        {run.scopes.slice(0, 4).join(" · ")}
                        {run.scopes.length > 4 ? ` +${run.scopes.length - 4}` : ""}
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <Card className="border-dashed">
        <CardContent className="p-3 text-xs text-muted-foreground">
          The refresh endpoint is signature-verified and refuses every request when no secret is
          configured, rather than defaulting to open — it is the one endpoint here that spends
          money. Runs are sequenced after the warehouse load and its quality gates, so a narrative
          can never describe a half-loaded warehouse while carrying the new vintage stamp.
        </CardContent>
      </Card>
    </div>
  );
}
