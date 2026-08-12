/**
 * Transfer & Conversion Intelligence Platform :: the metric catalogue.
 *
 * The governance layer, made browsable. Every KPI in the platform is registered
 * in `tr_gov.metric_definition` with an owner, a grain, a population, exclusions
 * and a version — and this screen renders that table verbatim.
 *
 * It has no editing affordance on purpose. Definitions are provisioned from
 * version control and reconciled by `tests/governance_checks.py`; a metric that
 * could be edited in a running instance is a metric that will differ between
 * environments and reappear as "whose number is right?" a quarter later.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader, Panel, QueryState } from "@/components/panels";
import { catalogueQuery } from "@/lib/marts";

export function CatalogueScreen() {
  const query = useQuery(catalogueQuery());
  const [search, setSearch] = React.useState("");

  const metrics = (query.data?.metrics ?? []).filter((metric) => {
    if (!search) return true;
    const needle = search.toLowerCase();
    return (
      metric.metric_code.toLowerCase().includes(needle) ||
      metric.business_name.toLowerCase().includes(needle) ||
      metric.definition.toLowerCase().includes(needle)
    );
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Metric catalogue"
        description="Every governed KPI, with its owner, grain, population and version. This is what the assistant resolves against, and what every panel footnote is read from."
      />

      <Card className="border-dashed">
        <CardContent className="p-3 text-xs text-muted-foreground">
          Definitions are provisioned from version control, never edited in a running instance.
          The reconciliation gate asserts that every registered metric has exactly one
          implementation and that no implementation bypasses this table — so a definition here and
          the number on a dashboard cannot drift apart.
        </CardContent>
      </Card>

      <Panel
        title={`${metrics.length} governed metrics`}
        actions={
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search definitions"
              className="pl-8"
              aria-label="Search the catalogue"
            />
          </div>
        }
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={metrics.length === 0}
          onRetry={() => void query.refetch()}
          rows={8}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                <TableHead>Definition</TableHead>
                <TableHead>Grain</TableHead>
                <TableHead>Population</TableHead>
                <TableHead>Excludes</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Served by</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {metrics.map((metric) => (
                <TableRow key={metric.metric_code}>
                  <TableCell>
                    <div className="num text-xs font-medium">{metric.metric_code}</div>
                    <div className="text-xs text-muted-foreground">{metric.business_name}</div>
                  </TableCell>
                  <TableCell className="num max-w-72 text-xs">{metric.definition}</TableCell>
                  <TableCell className="text-xs">{metric.grain}</TableCell>
                  <TableCell className="max-w-56 text-xs text-muted-foreground">
                    {metric.population}
                  </TableCell>
                  <TableCell className="max-w-40 text-xs text-muted-foreground">
                    {metric.exclusions}
                  </TableCell>
                  <TableCell className="text-xs">{metric.owner}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="num">
                      v{metric.version}
                    </Badge>
                  </TableCell>
                  <TableCell className="num text-xs text-muted-foreground">
                    {metric.endpoint ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>
    </div>
  );
}
