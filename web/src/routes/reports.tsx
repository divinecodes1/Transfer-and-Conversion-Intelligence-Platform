/**
 * Transfer & Conversion Intelligence Platform :: reporting.
 *
 * A print-ready summary of the current scope, a CSV of the same rows, and an
 * AI-drafted email for a named audience. The print stylesheet drops the
 * navigation and the chrome, so "print to PDF" produces the document rather than
 * a screenshot of an application.
 *
 * The narrative and the numbers come from the same snapshot and carry the same
 * vintage, which is the only reason it is safe to put them on one page.
 */
import { useQuery } from "@tanstack/react-query";
import { Download, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AiInsightCard, ReportEmailDraft } from "@/components/ai";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import { downloadCsv } from "@/lib/csv";
import {
  accuracyQuery,
  fmtDays,
  fmtNumber,
  fmtPercent,
  kpisQuery,
  projectsQuery,
  trendQuery,
} from "@/lib/marts";

export function ReportsScreen() {
  const { filters } = useFilters();
  const kpis = useQuery(kpisQuery(filters));
  const trend = useQuery(trendQuery(filters));
  const accuracy = useQuery(accuracyQuery(filters));
  const worst = useQuery(
    projectsQuery(filters, { sort_by: "schedule_deviation_days", descending: true, limit: 15 }),
  );

  const k = kpis.data?.kpis;
  const scope = Object.entries(kpis.data?.filters_applied ?? {});

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reports"
        description="A print-ready summary of the current scope, with the definitions and data vintage attached."
      >
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <Printer />
          Print
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            downloadCsv(
              `transfer-conversion-intelligence-platform-trend-${new Date().toISOString().slice(0, 10)}.csv`,
              (trend.data?.series ?? []) as unknown as Record<string, unknown>[],
            )
          }
          disabled={(trend.data?.series?.length ?? 0) === 0}
        >
          <Download />
          Export trend
        </Button>
      </PageHeader>

      <div className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-base font-semibold">Portfolio report</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Scope:{" "}
          {scope.length === 0
            ? "whole portfolio"
            : scope.map(([key, value]) => `${key.replace(/_/g, " ")} = ${value}`).join(", ")}
          {" · "}Data as of{" "}
          <span className="num">{String(kpis.data?.data_as_of ?? "—").slice(0, 10)}</span>
          {" · "}Generated {new Date().toLocaleString()}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="On-time" value={fmtPercent(k?.on_time_rate)} loading={kpis.isLoading} />
        <KpiTile label="Throughput" value={fmtNumber(k?.throughput)} loading={kpis.isLoading} />
        <KpiTile
          label="Median cycle"
          value={fmtNumber(k?.median_cycle_time)}
          unit="d"
          loading={kpis.isLoading}
        />
        <KpiTile label="WIP" value={fmtNumber(k?.wip)} loading={kpis.isLoading} />
        <KpiTile label="Replan rate" value={fmtPercent(k?.replan_rate)} loading={kpis.isLoading} />
        <KpiTile
          label="Late"
          value={fmtNumber(k?.delayed_count)}
          tone={k?.delayed_count ? "bad" : "ok"}
          loading={kpis.isLoading}
        />
      </div>

      <AiInsightCard
        kind="report_summary"
        title="Narrative summary"
        description="Steering-committee register, from the governed snapshot above."
        filters={filters}
      />

      <Panel title="Performance by fiscal year" envelope={trend.data}>
        <QueryState
          isLoading={trend.isLoading}
          error={trend.error}
          isEmpty={(trend.data?.series?.length ?? 0) === 0}
          onRetry={() => void trend.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fiscal year</TableHead>
                <TableHead>Throughput</TableHead>
                <TableHead>Median cycle time</TableHead>
                <TableHead>On-time rate</TableHead>
                <TableHead>Replan rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(trend.data?.series ?? []).map((row) => (
                <TableRow key={row.fiscal_year}>
                  <TableCell className="num">{row.fiscal_year}</TableCell>
                  <TableCell className="num">{fmtNumber(row.throughput)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.median_cycle_time)} d</TableCell>
                  <TableCell className="num">{fmtPercent(row.on_time_rate)}</TableCell>
                  <TableCell className="num">{fmtPercent(row.replan_rate)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <Panel title="Forecast reliability" envelope={accuracy.data}>
        <QueryState
          isLoading={accuracy.isLoading}
          error={accuracy.error}
          isEmpty={(accuracy.data?.series?.length ?? 0) === 0}
          onRetry={() => void accuracy.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Horizon</TableHead>
                <TableHead>n</TableHead>
                <TableHead>Median abs. error</TableHead>
                <TableHead>Bias</TableHead>
                <TableHead>Within 14 days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(accuracy.data?.series ?? []).map((row) => (
                <TableRow key={row.horizon_bucket}>
                  <TableCell className="num">{row.horizon_bucket} days out</TableCell>
                  <TableCell className="num">{row.n}</TableCell>
                  <TableCell className="num">{fmtNumber(row.median_abs_error)} d</TableCell>
                  <TableCell className="num">{fmtDays(row.bias)}</TableCell>
                  <TableCell className="num">{fmtPercent(row.within_14_days_pct)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <Panel title="Attention required" envelope={worst.data}>
        <QueryState
          isLoading={worst.isLoading}
          error={worst.error}
          isEmpty={(worst.data?.projects?.length ?? 0) === 0}
          onRetry={() => void worst.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Route</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Drift</TableHead>
                <TableHead>Revisions</TableHead>
                <TableHead>WIP age</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(worst.data?.projects ?? []).map((project) => (
                <TableRow key={project.project_id}>
                  <TableCell className="num">{project.project_id}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {project.source_site} → {project.target_site}
                  </TableCell>
                  <TableCell className="text-xs">{project.status}</TableCell>
                  <TableCell className="num">{fmtDays(project.schedule_deviation_days)}</TableCell>
                  <TableCell className="num">{fmtNumber(project.revision_count)}</TableCell>
                  <TableCell className="num">{fmtNumber(project.wip_age_days)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <ReportEmailDraft filters={filters} />
    </div>
  );
}
