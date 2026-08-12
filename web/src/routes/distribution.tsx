/**
 * Transfer & Conversion Intelligence Platform :: cycle-time distribution and schedule drift.
 *
 * The technical/PMO view. Distributions rather than averages, because the spread
 * is the thing the original reporting actually showed: a mean cycle time hides
 * the P90 tail that determines whether a site can commit to a date.
 *
 * Every chart ships with its table, so no value is reachable only by hovering.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AiInsightCard } from "@/components/ai";
import { BoxPlot, CohortBars, DriftBars } from "@/components/charts";
import { PageHeader, Panel, QueryState } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import {
  distributionQuery,
  fmtDays,
  fmtNumber,
  scheduleDriftQuery,
  stageCycleTimeQuery,
} from "@/lib/marts";

const COHORTS = [
  { value: "transfer_type", label: "Transfer type" },
  { value: "complexity_class", label: "Complexity" },
  { value: "target_site", label: "Target site" },
  { value: "source_site", label: "Source site" },
  { value: "portfolio", label: "Portfolio" },
  { value: "fiscal_year", label: "Fiscal year" },
];

export function DistributionScreen() {
  const { filters } = useFilters();
  const [cohort, setCohort] = React.useState("transfer_type");
  const distribution = useQuery(distributionQuery(filters, cohort));
  const drift = useQuery(scheduleDriftQuery(filters, "transfer_type"));
  const stages = useQuery(stageCycleTimeQuery());

  const rows = distribution.data?.series ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Cycle-time distribution"
        description="Percentiles per cohort. The spread is the point — an average duration tells a site nothing about the date it can safely commit to."
      />

      <Panel
        title="Cycle time by cohort"
        description="Box: P25 to P75, thick line the median, dashed the P90, whiskers min to max."
        envelope={distribution.data}
        actions={
          <Tabs value={cohort} onValueChange={setCohort}>
            <TabsList>
              {COHORTS.map((option) => (
                <TabsTrigger key={option.value} value={option.value}>
                  {option.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      >
        <QueryState
          isLoading={distribution.isLoading}
          error={distribution.error}
          isEmpty={rows.length === 0}
          onRetry={() => void distribution.refetch()}
          rows={6}
        >
          <div className="overflow-x-auto">
            <BoxPlot rows={rows} />
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cohort</TableHead>
                <TableHead>n</TableHead>
                <TableHead>Min</TableHead>
                <TableHead>P25</TableHead>
                <TableHead>Median</TableHead>
                <TableHead>P75</TableHead>
                <TableHead>P90</TableHead>
                <TableHead>Max</TableHead>
                <TableHead>IQR</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.cohort}>
                  <TableCell>{row.cohort}</TableCell>
                  <TableCell className="num">{row.n}</TableCell>
                  <TableCell className="num">{fmtNumber(row.min_days)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.p25)}</TableCell>
                  <TableCell className="num font-medium">{fmtNumber(row.p50)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.p75)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.p90)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.max_days)}</TableCell>
                  <TableCell className="num">{fmtNumber(row.iqr)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Schedule drift either side of the baseline"
          description="Median movement from the frozen commitment. Above the line is slip; below it is a plan that pulled in."
          envelope={drift.data}
        >
          <QueryState
            isLoading={drift.isLoading}
            error={drift.error}
            isEmpty={(drift.data?.series?.length ?? 0) === 0}
            onRetry={() => void drift.refetch()}
          >
            <DriftBars
              data={(drift.data?.series ?? []) as unknown as Record<string, unknown>[]}
              x="group_value"
              y="median"
              name="Median drift"
            />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cohort</TableHead>
                  <TableHead>n</TableHead>
                  <TableHead>Median drift</TableHead>
                  <TableHead>P75</TableHead>
                  <TableHead>P90</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(drift.data?.series ?? []).map((row) => (
                  <TableRow key={row.group_value}>
                    <TableCell>{row.group_value}</TableCell>
                    <TableCell className="num">{row.n}</TableCell>
                    <TableCell className="num">{fmtDays(row.median)}</TableCell>
                    <TableCell className="num">{fmtDays(row.p75)}</TableCell>
                    <TableCell className="num">{fmtDays(row.p90)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </QueryState>
        </Panel>

        <Panel
          title="Where the time goes, stage by stage"
          description="Milestone-to-milestone durations. This is where a delay is created, rather than only that the total is large."
          envelope={stages.data}
        >
          <QueryState
            isLoading={stages.isLoading}
            error={stages.error}
            isEmpty={(stages.data?.series?.length ?? 0) === 0}
            onRetry={() => void stages.refetch()}
          >
            <CohortBars
              data={(stages.data?.series ?? []).map((row) => ({
                stage: `${row.from_stage}→${row.to_stage}`,
                median: row.median,
              }))}
              x="stage"
              y="median"
              name="Median stage duration"
              unit=" d"
            />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stage</TableHead>
                  <TableHead>n</TableHead>
                  <TableHead>Median</TableHead>
                  <TableHead>P90</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(stages.data?.series ?? []).map((row) => (
                  <TableRow key={`${row.from_stage}-${row.to_stage}`}>
                    <TableCell className="text-xs">
                      {row.from_stage} → {row.to_stage}
                    </TableCell>
                    <TableCell className="num">{row.n}</TableCell>
                    <TableCell className="num">{fmtNumber(row.median)} d</TableCell>
                    <TableCell className="num">{fmtNumber(row.p90)} d</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </QueryState>
        </Panel>
      </div>

      <AiInsightCard
        kind="anomaly_watch"
        title="Anomaly watch"
        description="Movement in this scope worth an alert."
        filters={filters}
      />
    </div>
  );
}
