/**
 * Transfer & Conversion Intelligence Platform :: transfer readiness.
 *
 * The question this screen answers is not "how is the portfolio doing?" — three
 * other screens answer that — but "what is not ready, and what specifically is
 * holding it back?". Readiness is a leading indicator: a schedule deviation is
 * news about a decision already made, while a qualification dimension sitting at
 * 61% is news about a decision still available.
 *
 * Everything numeric here arrives from the API. The seven weights, the weighted
 * mean and the READY / AT_RISK / NOT_READY boundaries all live in
 * sql/13_readiness_network.sql; this file renders them and re-derives none of
 * them, which is what tests/web_checks.py asserts.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ClipboardCheck, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FilterBar } from "@/components/FilterBar";
import { KpiTile, PageHeader, Panel, QueryState, ReadinessBadge } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import {
  fmtDays,
  fmtNumber,
  fmtPercent,
  readinessDimensionsQuery,
  readinessQuery,
} from "@/lib/marts";

export function ReadinessScreen() {
  const { filters } = useFilters();
  const register = useQuery(readinessQuery(filters));
  const dimensions = useQuery(readinessDimensionsQuery(filters));

  const summary = register.data?.summary;
  const rows = register.data?.projects ?? [];
  const dims = dimensions.data?.dimensions ?? [];
  // The API returns dimensions weakest-first, so the portfolio's binding
  // constraint is simply the first row. Not recomputed here on purpose.
  const weakest = dims[0];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Transfer readiness"
        description="How prepared the in-flight portfolio is to execute, by weighted dimension. Assessed for active and planned transfers only — a completed transfer has an outcome, not a readiness."
      />

      <FilterBar />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          label="Average readiness"
          value={fmtPercent(summary?.avg_readiness_pct)}
          hint={`${fmtNumber(summary?.projects)} in-flight transfers`}
          loading={register.isLoading}
        />
        <KpiTile
          label="Ready"
          value={fmtNumber(summary?.ready_count)}
          tone="ok"
          hint="Above the ready threshold"
          loading={register.isLoading}
        />
        <KpiTile
          label="At risk"
          value={fmtNumber(summary?.at_risk_count)}
          tone="warn"
          hint="Below ready, above the floor"
          loading={register.isLoading}
        />
        <KpiTile
          label="Not ready"
          value={fmtNumber(summary?.not_ready_count)}
          tone="bad"
          hint="Below the readiness floor"
          loading={register.isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Readiness by dimension"
          description="Portfolio average per dimension, weakest first. The weight is what each dimension contributes to the overall score."
          envelope={dimensions.data}
        >
          <QueryState
            isLoading={dimensions.isLoading}
            error={dimensions.error}
            isEmpty={dims.length === 0}
            onRetry={() => void dimensions.refetch()}
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Dimension</TableHead>
                  <TableHead className="text-right">Weight</TableHead>
                  <TableHead className="text-right">Average</TableHead>
                  <TableHead className="text-right">Lowest</TableHead>
                  <TableHead className="text-right">Below 70</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dims.map((dim) => (
                  <TableRow key={dim.dimension_code}>
                    <TableCell className="font-medium">{dim.dimension_name}</TableCell>
                    <TableCell className="num text-right text-muted-foreground">
                      {fmtNumber(dim.weight_pct)}%
                    </TableCell>
                    <TableCell className="num text-right">
                      {fmtPercent(dim.avg_score_pct)}
                    </TableCell>
                    <TableCell className="num text-right text-muted-foreground">
                      {fmtNumber(dim.min_score_pct)}
                    </TableCell>
                    <TableCell className="num text-right">
                      {fmtNumber(dim.below_70)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </QueryState>
        </Panel>

        <Panel
          title="Where the portfolio is constrained"
          description="The dimension with the lowest average across every in-flight transfer in scope."
          envelope={dimensions.data}
        >
          <QueryState
            isLoading={dimensions.isLoading}
            error={dimensions.error}
            isEmpty={!weakest}
            onRetry={() => void dimensions.refetch()}
          >
            {weakest ? (
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="grid size-10 shrink-0 place-items-center rounded-md bg-accent text-primary">
                    <TriangleAlert className="size-5" />
                  </div>
                  <div>
                    <div className="text-lg font-semibold">{weakest.dimension_name}</div>
                    <div className="text-sm text-muted-foreground">
                      Averaging <span className="num">{fmtPercent(weakest.avg_score_pct)}</span>{" "}
                      across <span className="num">{fmtNumber(weakest.projects)}</span> transfers,
                      and carrying <span className="num">{fmtNumber(weakest.weight_pct)}%</span> of
                      the overall score.
                    </div>
                  </div>
                </div>

                <p className="text-sm leading-6 text-muted-foreground">
                  <span className="num">{fmtNumber(weakest.below_70)}</span> transfers score below
                  70 on this dimension. Because it is the heaviest constraint in scope, it is also
                  the dimension where a fixed transfer moves the portfolio number most.
                </p>

                <div className="rounded-md border border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                  Assessments in this scope are on average{" "}
                  <span className="num">{fmtNumber(summary?.avg_assessment_age_days)}</span> days
                  old, measured against the warehouse vintage rather than the clock. A readiness
                  score nobody has revisited is not evidence about today.
                </div>
              </div>
            ) : null}
          </QueryState>
        </Panel>
      </div>

      <Panel
        title="Transfers by readiness"
        description="Least ready first — the ordering this screen exists for."
        envelope={register.data}
        actions={
          <Badge variant="muted">
            <ClipboardCheck className="mr-1 size-3.5" />
            {fmtNumber(rows.length)} shown
          </Badge>
        }
      >
        <QueryState
          isLoading={register.isLoading}
          error={register.error}
          isEmpty={rows.length === 0}
          emptyMessage="No in-flight transfers in this scope."
          onRetry={() => void register.refetch()}
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Transfer</TableHead>
                  <TableHead>Route</TableHead>
                  <TableHead className="text-right">Readiness</TableHead>
                  <TableHead>Band</TableHead>
                  <TableHead>Limiting dimension</TableHead>
                  <TableHead className="text-right">Drift</TableHead>
                  <TableHead className="text-right">Assessed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.project_id}>
                    <TableCell>
                      <Link
                        to="/projects/$projectId"
                        params={{ projectId: row.project_id }}
                        className="num font-medium text-primary hover:underline"
                      >
                        {row.project_id}
                      </Link>
                      <div className="text-xs text-muted-foreground">{row.project_name}</div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {row.source_site} → {row.target_site}
                    </TableCell>
                    <TableCell className="num text-right font-semibold">
                      {fmtPercent(row.readiness_pct)}
                    </TableCell>
                    <TableCell>
                      <ReadinessBadge band={row.readiness_band} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {row.limiting_dimension_name ?? "—"}
                      {row.limiting_score !== null ? (
                        <span className="num ml-1 text-muted-foreground">
                          ({fmtNumber(row.limiting_score)})
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="num text-right text-muted-foreground">
                      {fmtDays(row.schedule_deviation_days)}
                    </TableCell>
                    <TableCell className="num text-right text-muted-foreground">
                      {fmtNumber(row.assessment_age_days)}d ago
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </QueryState>
      </Panel>
    </div>
  );
}
