/**
 * Transfer & Conversion Intelligence Platform :: portfolio overview.
 *
 * The management view: one number that matters most, then the health bands, the
 * trend, and where the risk is concentrated — with the AI briefing beside them
 * rather than in place of them.
 *
 * The tiles lead with on-time completion because that is the metric the
 * portfolio is actually judged on. Throughput and cycle time explain it; they do
 * not replace it.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowUpRight, CheckCircle2, Eye, Telescope } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AiInsightCard, RiskBadge, useRiskScores } from "@/components/ai";
import { CohortBars, TrendChart } from "@/components/charts";
import { HealthBadge, KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import {
  distributionQuery,
  fmtDays,
  fmtNumber,
  fmtPercent,
  kpisQuery,
  projectsQuery,
  trendQuery,
  type DistributionRow,
} from "@/lib/marts";

export function OverviewScreen() {
  const { filters } = useFilters();
  const kpis = useQuery(kpisQuery(filters));
  const trend = useQuery(trendQuery(filters));
  const distribution = useQuery(distributionQuery(filters, "transfer_type"));
  const worst = useQuery(
    projectsQuery(filters, { sort_by: "schedule_deviation_days", descending: true, limit: 8 }),
  );
  const risk = useRiskScores();

  const k = kpis.data?.kpis;
  const slowestCohort = (distribution.data?.series ?? []).reduce<DistributionRow | null>(
    (current, row) => {
      if (row.p50 == null) return current;
      if (!current || current.p50 == null || row.p50 > current.p50) return row;
      return current;
    },
    null,
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Transfer & Conversion Command Center"
        description="Portfolio performance, operational risk and management priorities across the governed transfer landscape."
      />

      <Card className="overflow-hidden border-primary/20">
        <CardContent className="grid p-0 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              label: "What",
              icon: Eye,
              value: `${fmtNumber(k?.delayed_count)} projects require attention`,
              detail: `${fmtNumber(k?.total_projects)} projects in the current scope`,
            },
            {
              label: "Why",
              icon: AlertTriangle,
              value: slowestCohort
                ? `${slowestCohort.cohort} has the longest median cycle`
                : "Cohort analysis is loading",
              detail: slowestCohort
                ? `${fmtNumber(slowestCohort.p50)} days median`
                : "Governed metric analysis",
            },
            {
              label: "Next",
              icon: Telescope,
              value: `${fmtNumber(k?.wip)} active transfers remain in progress`,
              detail: `Median WIP age ${fmtNumber(k?.median_wip_age)} days`,
            },
            {
              label: "Action",
              icon: CheckCircle2,
              value: "Review the management attention list",
              detail: "Prioritise high drift and repeated replanning",
            },
          ].map((item, index) => {
            const Icon = item.icon;
            return (
              <div
                key={item.label}
                className={
                  index === 0
                    ? "p-4"
                    : "border-t border-border p-4 sm:border-l sm:border-t-0"
                }
              >
                <div className="flex items-center gap-2 text-label uppercase text-primary">
                  <Icon className="size-3.5" /> {item.label}
                </div>
                <div className="mt-2 text-sm font-semibold">{item.value}</div>
                <div className="mt-1 text-xs text-muted-foreground">{item.detail}</div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <AiInsightCard
        kind="portfolio_overview"
        title="AI management brief"
        description="What changed, where risk is concentrated and what management should do next—using the current governed scope."
        filters={filters}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiTile
          label="On-time rate"
          value={fmtPercent(k?.on_time_rate)}
          hint="Finished on or before the frozen baseline"
          tone={
            k?.on_time_rate == null
              ? "neutral"
              : k.on_time_rate >= 70
                ? "ok"
                : k.on_time_rate >= 50
                  ? "warn"
                  : "bad"
          }
          loading={kpis.isLoading}
        />
        <KpiTile
          label="Throughput"
          value={fmtNumber(k?.throughput)}
          hint="Projects completed in scope"
          loading={kpis.isLoading}
        />
        <KpiTile
          label="Median cycle time"
          value={fmtNumber(k?.median_cycle_time)}
          unit="d"
          hint={`P90 ${fmtNumber(k?.p90_cycle_time)} d`}
          loading={kpis.isLoading}
        />
        <KpiTile
          label="WIP"
          value={fmtNumber(k?.wip)}
          hint={`Median age ${fmtNumber(k?.median_wip_age)} d`}
          loading={kpis.isLoading}
        />
        <KpiTile
          label="Replan rate"
          value={fmtPercent(k?.replan_rate)}
          hint="More than one schedule revision"
          tone={
            k?.replan_rate == null ? "neutral" : k.replan_rate >= 60 ? "warn" : "neutral"
          }
          loading={kpis.isLoading}
        />
        <KpiTile
          label="Delayed / at risk"
          value={fmtNumber(k?.delayed_count)}
          hint={`of ${fmtNumber(k?.total_projects)} in scope`}
          tone={k?.delayed_count ? "bad" : "ok"}
          loading={kpis.isLoading}
        />
      </div>

      <div className="order-2 grid gap-4 lg:grid-cols-2">
        <Panel
          title="Throughput and delivery quality by fiscal year"
          description="Completed projects, on-time delivery and replanning over time."
          envelope={trend.data}
        >
          <QueryState
            isLoading={trend.isLoading}
            error={trend.error}
            isEmpty={(trend.data?.series?.length ?? 0) === 0}
            onRetry={() => void trend.refetch()}
          >
            <TrendChart
              data={(trend.data?.series ?? []) as unknown as Record<string, unknown>[]}
              x="fiscal_year"
              series={[
                { key: "on_time_rate", name: "On-time %" },
                { key: "replan_rate", name: "Replan %" },
                { key: "throughput", name: "Throughput" },
              ]}
            />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fiscal year</TableHead>
                  <TableHead>Throughput</TableHead>
                  <TableHead>Median cycle</TableHead>
                  <TableHead>On-time</TableHead>
                  <TableHead>Replan</TableHead>
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

        <Panel
          title="Median cycle time by transfer type"
          description="Where the duration actually sits, per cohort."
          envelope={distribution.data}
        >
          <QueryState
            isLoading={distribution.isLoading}
            error={distribution.error}
            isEmpty={(distribution.data?.series?.length ?? 0) === 0}
            onRetry={() => void distribution.refetch()}
          >
            <CohortBars
              data={(distribution.data?.series ?? []) as unknown as Record<string, unknown>[]}
              x="cohort"
              y="p50"
              name="Median cycle time"
              unit=" d"
            />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cohort</TableHead>
                  <TableHead>n</TableHead>
                  <TableHead>P25</TableHead>
                  <TableHead>Median</TableHead>
                  <TableHead>P75</TableHead>
                  <TableHead>P90</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(distribution.data?.series ?? []).map((row) => (
                  <TableRow key={row.cohort}>
                    <TableCell>{row.cohort}</TableCell>
                    <TableCell className="num">{row.n}</TableCell>
                    <TableCell className="num">{fmtNumber(row.p25)}</TableCell>
                    <TableCell className="num">{fmtNumber(row.p50)}</TableCell>
                    <TableCell className="num">{fmtNumber(row.p75)}</TableCell>
                    <TableCell className="num">{fmtNumber(row.p90)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </QueryState>
        </Panel>
      </div>

      <Panel
        className="order-1"
        title="Management attention"
        description="Transfers requiring review because schedule movement, age or repeated replanning has crossed the current priority threshold."
        envelope={worst.data}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/projects">
              All projects
              <ArrowUpRight />
            </Link>
          </Button>
        }
      >
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
                <TableHead>Type</TableHead>
                <TableHead>Route</TableHead>
                <TableHead>Health</TableHead>
                <TableHead>Drift</TableHead>
                <TableHead>Revisions</TableHead>
                {risk.enabled ? <TableHead>Delay risk</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {(worst.data?.projects ?? []).map((project) => (
                <TableRow key={project.project_id}>
                  <TableCell>
                    <Link
                      to="/projects/$projectId"
                      params={{ projectId: project.project_id }}
                      className="num text-primary hover:underline"
                    >
                      {project.project_id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs">{project.transfer_type}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {project.source_site} → {project.target_site}
                  </TableCell>
                  <TableCell>
                    <HealthBadge health={project.health} />
                  </TableCell>
                  <TableCell className="num">
                    {fmtDays(project.schedule_deviation_days)}
                  </TableCell>
                  <TableCell className="num">{fmtNumber(project.revision_count)}</TableCell>
                  {risk.enabled ? (
                    <TableCell>
                      <RiskBadge score={risk.byProject.get(project.project_id)} />
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>
    </div>
  );
}
