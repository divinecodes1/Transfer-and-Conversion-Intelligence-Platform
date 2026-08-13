/**
 * Transfer & Conversion Intelligence Platform :: the project register.
 *
 * Sortable, searchable, filter-scoped, with the health band and the model's
 * delay-risk estimate side by side — deliberately adjacent, so a reader can see
 * where the two disagree. The band is a governed rule; the risk is an opinion.
 *
 * Sorting happens in the API, not here. Sorting a truncated page in the browser
 * shows the worst of what happened to be fetched and calls it the worst in the
 * portfolio.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Download, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RiskBadge, useRiskScores } from "@/components/ai";
import { HealthBadge, PageHeader, Panel, QueryState } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import { downloadCsv } from "@/lib/csv";
import { fmtDate, fmtDays, fmtNumber, projectsQuery, type ProjectRow } from "@/lib/marts";

const COLUMNS: { key: string; label: string; sortable?: boolean; numeric?: boolean }[] = [
  { key: "project_id", label: "Project", sortable: true },
  { key: "transfer_type", label: "Type" },
  { key: "route", label: "Route" },
  { key: "status", label: "Status" },
  { key: "health", label: "Health", sortable: true },
  { key: "schedule_deviation_days", label: "Drift", sortable: true, numeric: true },
  { key: "actual_cycle_time_days", label: "Cycle time", sortable: true, numeric: true },
  { key: "wip_age_days", label: "WIP age", sortable: true, numeric: true },
  { key: "revision_count", label: "Revisions", sortable: true, numeric: true },
  { key: "baseline_finish", label: "Baseline finish" },
];

export function ProjectsScreen() {
  const { filters } = useFilters();
  const [search, setSearch] = React.useState(
    () => new URLSearchParams(window.location.search).get("search") ?? "",
  );
  const [debounced, setDebounced] = React.useState(search);
  const [sortBy, setSortBy] = React.useState("schedule_deviation_days");
  const [descending, setDescending] = React.useState(true);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const query = useQuery(
    projectsQuery(filters, { search: debounced || undefined, sort_by: sortBy, descending }),
  );
  const risk = useRiskScores();
  const rows = query.data?.projects ?? [];

  const toggleSort = (key: string) => {
    if (sortBy === key) setDescending((value) => !value);
    else {
      setSortBy(key);
      setDescending(true);
    }
  };

  const exportRows = () =>
    downloadCsv(
      `transfer-conversion-intelligence-platform-projects-${new Date().toISOString().slice(0, 10)}.csv`,
      rows as unknown as Record<string, unknown>[],
    );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Transfer Portfolio"
        description="Search, compare and prioritise governed transfer-project records. Schedule variance is measured against the frozen baseline."
      >
        <Button variant="outline" size="sm" onClick={exportRows} disabled={rows.length === 0}>
          <Download />
          Export CSV
        </Button>
      </PageHeader>

      <Panel
        title={`${fmtNumber(query.data?.total_matching)} projects in scope`}
        envelope={query.data}
        actions={
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search id, name or site"
              className="pl-8"
              aria-label="Search projects"
            />
          </div>
        }
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={rows.length === 0}
          emptyMessage={
            debounced
              ? "No project matches that search in this scope."
              : "No projects in this scope. If you are not an administrator, this may be entitlement scoping working as designed."
          }
          onRetry={() => void query.refetch()}
          rows={8}
        >
          <Table>
            <TableHeader className="border-t border-border bg-card">
              <TableRow>
                {COLUMNS.map((column) => (
                  <TableHead key={column.key}>
                    {column.sortable ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(column.key)}
                        className="inline-flex items-center gap-1 hover:text-foreground"
                      >
                        {column.label}
                        {sortBy === column.key ? (
                          descending ? (
                            <ArrowDown className="size-3" />
                          ) : (
                            <ArrowUp className="size-3" />
                          )
                        ) : null}
                      </button>
                    ) : (
                      column.label
                    )}
                  </TableHead>
                ))}
                {risk.enabled ? <TableHead>Delay risk</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((project: ProjectRow) => (
                <TableRow key={project.project_id}>
                  <TableCell>
                    <Link
                      to="/projects/$projectId"
                      params={{ projectId: project.project_id }}
                      className="num text-primary hover:underline"
                    >
                      {project.project_id}
                    </Link>
                    <div className="text-xs text-muted-foreground">{project.project_name}</div>
                  </TableCell>
                  <TableCell className="text-xs">{project.transfer_type}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {project.source_site} → {project.target_site}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{project.status}</Badge>
                  </TableCell>
                  <TableCell>
                    <HealthBadge health={project.health} />
                  </TableCell>
                  <TableCell className="num">
                    {fmtDays(project.schedule_deviation_days)}
                  </TableCell>
                  <TableCell className="num">
                    {fmtNumber(project.actual_cycle_time_days)}
                  </TableCell>
                  <TableCell className="num">{fmtNumber(project.wip_age_days)}</TableCell>
                  <TableCell className="num">{fmtNumber(project.revision_count)}</TableCell>
                  <TableCell className="num">{fmtDate(project.baseline_finish)}</TableCell>
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
