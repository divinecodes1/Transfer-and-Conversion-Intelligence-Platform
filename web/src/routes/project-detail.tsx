/**
 * Transfer & Conversion Intelligence Platform :: one project, and its preserved history.
 *
 * This screen only exists because the warehouse keeps history explicitly. Every
 * replan is a row in `fact_schedule_revision` and every forecast is a row in
 * `fact_project_snapshot`, so "how far has the plan moved, and when did it
 * move?" is a query rather than a lost fact.
 *
 * The baseline is drawn as a fixed reference line and every revision is plotted
 * against it. Plotting revisions against each other would show a plan that
 * always looks nearly on target — which is exactly the illusion that measuring
 * against the latest replan creates.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
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
import { RiskBadge, useRiskScores } from "@/components/ai";
import { TrendChart } from "@/components/charts";
import { HealthBadge, KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { fmtDate, fmtDays, fmtNumber, projectDetailQuery } from "@/lib/marts";

/** Band -> tile colour. The band itself is decided in SQL; this only paints it. */
const HEALTH_TONE = {
  ON_TRACK: "ok",
  AT_RISK: "warn",
  LATE: "bad",
  UNKNOWN: "neutral",
} as const;

function days(from: string | null | undefined, to: string | null | undefined) {
  if (!from || !to) return null;
  return Math.round(
    (new Date(to).getTime() - new Date(from).getTime()) / (1000 * 60 * 60 * 24),
  );
}

export function ProjectDetailScreen({ projectId }: { projectId: string }) {
  const query = useQuery(projectDetailQuery(projectId));
  const risk = useRiskScores();
  const project = query.data?.project;
  const revisions = query.data?.schedule_revisions ?? [];
  const baseline = revisions.find((revision) => revision.is_baseline);

  // Each revision expressed as movement away from the frozen baseline finish.
  const drift = revisions.map((revision, index) => ({
    revision: revision.is_baseline ? "baseline" : `rev ${index}`,
    planned_finish_drift: days(baseline?.planned_finish, revision.planned_finish) ?? 0,
    forecast_finish_drift: days(baseline?.planned_finish, revision.forecast_finish) ?? 0,
  }));

  const snapshots = (query.data?.snapshots ?? []).map((snapshot) => ({
    snapshot_date: String(snapshot.snapshot_date).slice(0, 10),
    forecast_drift: days(baseline?.planned_finish, snapshot.forecast_finish) ?? 0,
  }));

  return (
    <div className="space-y-4">
      <PageHeader
        title={projectId}
        description={project?.project_name ?? "Schedule history, drift and milestones."}
      >
        <Button asChild variant="outline" size="sm">
          <Link to="/projects">
            <ArrowLeft />
            Register
          </Link>
        </Button>
      </PageHeader>

      <QueryState
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        rows={6}
      >
        {project ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{project.status}</Badge>
              <HealthBadge health={project.health} />
              <Badge variant="secondary">{project.transfer_type}</Badge>
              <Badge variant="secondary">{project.complexity_class}</Badge>
              <Badge variant="secondary">{project.portfolio}</Badge>
              <span className="text-sm text-muted-foreground">
                {project.source_site} → {project.target_site}
              </span>
              {risk.enabled ? (
                <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                  Delay risk (model estimate):
                  <RiskBadge score={risk.byProject.get(projectId)} />
                </span>
              ) : null}
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <KpiTile
                label="Baseline finish"
                value={fmtDate(project.baseline_finish)}
                hint="Frozen commitment"
              />
              <KpiTile label="Latest planned" value={fmtDate(project.latest_finish)} />
              <KpiTile
                label="Schedule drift"
                value={fmtDays(project.schedule_deviation_days)}
                hint="Latest plan vs baseline"
                // The tone follows the governed health band, not a day count
                // re-applied here. The threshold lives once, in the mart.
                tone={HEALTH_TONE[project.health] ?? "neutral"}
              />
              <KpiTile
                label="Actual finish"
                value={fmtDate(project.actual_finish)}
                hint={
                  project.completion_variance_days == null
                    ? "In flight"
                    : `${fmtDays(project.completion_variance_days)} vs baseline`
                }
              />
              <KpiTile
                label="Cycle time"
                value={fmtNumber(project.actual_cycle_time_days)}
                unit="d"
                hint={
                  project.wip_age_days ? `WIP age ${fmtNumber(project.wip_age_days)} d` : undefined
                }
              />
              <KpiTile
                label="Revisions"
                value={fmtNumber(project.revision_count)}
                hint={project.was_replanned ? "Replanned" : "Never replanned"}
                tone={(project.revision_count ?? 0) > 3 ? "warn" : "neutral"}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Panel
                title="Schedule drift against the frozen baseline"
                description="Every preserved replan, measured from the original commitment — not from the previous replan."
              >
                {drift.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No schedule revisions held.</p>
                ) : (
                  <>
                    <TrendChart
                      data={drift as unknown as Record<string, unknown>[]}
                      x="revision"
                      series={[
                        { key: "planned_finish_drift", name: "Planned finish drift (d)" },
                        { key: "forecast_finish_drift", name: "Forecast finish drift (d)" },
                      ]}
                      unit=" d"
                    />
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>When</TableHead>
                          <TableHead>Reason</TableHead>
                          <TableHead>Planned finish</TableHead>
                          <TableHead>Forecast finish</TableHead>
                          <TableHead>Drift</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {revisions.map((revision) => (
                          <TableRow key={revision.revision_id}>
                            <TableCell className="num text-xs">
                              {String(revision.revision_timestamp).slice(0, 10)}
                            </TableCell>
                            <TableCell>
                              <Badge variant={revision.is_baseline ? "default" : "outline"}>
                                {revision.revision_reason}
                              </Badge>
                            </TableCell>
                            <TableCell className="num">
                              {fmtDate(revision.planned_finish)}
                            </TableCell>
                            <TableCell className="num">
                              {fmtDate(revision.forecast_finish)}
                            </TableCell>
                            <TableCell className="num">
                              {fmtDays(days(baseline?.planned_finish, revision.planned_finish))}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
              </Panel>

              <Panel
                title="What we believed, month by month"
                description="Forecast finish at each snapshot, against the baseline. This history is what makes forecast accuracy measurable at all."
              >
                {snapshots.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No snapshots held.</p>
                ) : (
                  <TrendChart
                    data={snapshots as unknown as Record<string, unknown>[]}
                    x="snapshot_date"
                    series={[{ key: "forecast_drift", name: "Forecast drift vs baseline (d)" }]}
                    unit=" d"
                  />
                )}
              </Panel>
            </div>

            <Panel
              title="Milestones"
              description="Where in the transfer process the time actually went."
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Milestone</TableHead>
                    <TableHead>Planned</TableHead>
                    <TableHead>Actual</TableHead>
                    <TableHead>Slip</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(query.data?.milestones ?? []).map((milestone) => (
                    <TableRow key={milestone.milestone_code}>
                      <TableCell className="num">{milestone.sequence_no}</TableCell>
                      <TableCell>
                        {milestone.milestone_name}
                        <span className="num ml-2 text-xs text-muted-foreground">
                          {milestone.milestone_code}
                        </span>
                      </TableCell>
                      <TableCell className="num">{fmtDate(milestone.planned_date)}</TableCell>
                      <TableCell className="num">{fmtDate(milestone.actual_date)}</TableCell>
                      <TableCell className="num">
                        {fmtDays(days(milestone.planned_date, milestone.actual_date))}
                      </TableCell>
                      <TableCell>
                        <Badge variant={milestone.event_status === "REACHED" ? "ok" : "muted"} dot>
                          {milestone.event_status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Panel>

            <Card>
              <CardContent className="p-3 text-xs text-muted-foreground">
                Data as of{" "}
                <span className="num">{String(query.data?.data_as_of ?? "—").slice(0, 10)}</span>.
                Drift and variance are both measured from the immutable baseline revision, which
                is why a replan cannot improve this project&apos;s score.
              </CardContent>
            </Card>
          </>
        ) : null}
      </QueryState>
    </div>
  );
}
