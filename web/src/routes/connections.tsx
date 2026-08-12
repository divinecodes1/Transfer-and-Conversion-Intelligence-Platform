/**
 * Transfer & Conversion Intelligence Platform :: connections — how other tools reach this data.
 *
 * The reference console this was modelled on carries a two-way Tableau
 * integration: pull workbooks in, publish token-secured feeds out. This platform
 * takes the other side of that trade deliberately, and it is worth being
 * explicit about which:
 *
 * The mart layer **is** the BI contract. Tableau, Superset or anything else
 * consumes `tr_mart` through the governed API, so a workbook cannot recompute a
 * KPI its own way — which is the accreted-reporting failure the renovation
 * exists to undo. A second, private outbound feed with its own token and its own
 * shape would be a parallel definition surface, and inbound workbook sync would
 * put someone else's calculation logic back inside the platform.
 *
 * So this screen is a **connection catalogue**: every governed endpoint another
 * tool may consume, with the identity model that applies and a live check that
 * it is answering. It is honest about what it is not — see the note at the foot.
 */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Copy, ExternalLink, Link2, XCircle } from "lucide-react";
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
import { useAiEnabled } from "@/components/ai";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { useConnection } from "@/lib/app-state";
import { catalogueQuery, healthQuery } from "@/lib/marts";

const FEEDS = [
  {
    path: "/mart/projects",
    name: "Project register",
    shape: "One governed row per live project, with the health band.",
  },
  {
    path: "/mart/kpis",
    name: "Portfolio KPIs",
    shape: "Single-row rollup for the filter scope.",
  },
  {
    path: "/mart/trend",
    name: "Fiscal-year trend",
    shape: "Throughput, cycle time, on-time and replan rate per year.",
  },
  {
    path: "/mart/distribution",
    name: "Cycle-time distribution",
    shape: "Percentiles per cohort — the box-plot source.",
  },
  {
    path: "/mart/accuracy",
    name: "Forecast accuracy",
    shape: "Error and hit rate bucketed by horizon.",
  },
  {
    path: "/catalogue",
    name: "Metric catalogue",
    shape: "Every governed definition, with the endpoint that serves it.",
  },
];

export function ConnectionsScreen() {
  const health = useQuery(healthQuery());
  const catalogue = useQuery(catalogueQuery());
  const { mode, online, syncedAt } = useConnection();
  const { enabled: aiEnabled, status } = useAiEnabled();

  const base = import.meta.env["VITE_TRANSFEROPS_API"] ?? "/api";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Connections"
        description="Everything that reads this platform, and the one contract they all read it through."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          label="Analytics API"
          value={health.data?.status === "healthy" ? "Healthy" : health.isError ? "Unreachable" : "—"}
          hint={
            health.data?.projects !== undefined
              ? `${health.data.projects} projects visible to you`
              : undefined
          }
          tone={health.data?.status === "healthy" ? "ok" : health.isError ? "bad" : "neutral"}
          loading={health.isLoading}
        />
        <KpiTile
          label="Data vintage"
          value={String(health.data?.data_as_of ?? "—").slice(0, 10)}
          hint="Newest project snapshot held"
          loading={health.isLoading}
        />
        <KpiTile
          label="Browser mode"
          value={mode === "live" && online ? "Live" : "Offline"}
          hint={
            mode === "live" && online
              ? "Querying the API directly"
              : syncedAt
                ? `Snapshot from ${new Date(syncedAt).toLocaleTimeString()}`
                : "No snapshot yet"
          }
          tone={mode === "live" && online ? "ok" : "warn"}
        />
        <KpiTile
          label="AI provider"
          value={aiEnabled ? (status?.ai.provider ?? "configured") : "Not configured"}
          hint={aiEnabled ? (status?.ai.model ?? undefined) : "AI panels are hidden"}
          tone={aiEnabled ? "ok" : "neutral"}
        />
      </div>

      <Panel
        title="Governed feeds"
        description="What an external tool connects to. Every one of these returns the provenance envelope alongside the rows, so a workbook can print the same definition and vintage the console does."
      >
        <QueryState
          isLoading={catalogue.isLoading}
          error={catalogue.error}
          onRetry={() => void catalogue.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Feed</TableHead>
                <TableHead>Endpoint</TableHead>
                <TableHead>Returns</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {FEEDS.map((feed) => (
                <TableRow key={feed.path}>
                  <TableCell className="text-xs font-medium">{feed.name}</TableCell>
                  <TableCell className="num text-xs">{feed.path}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{feed.shape}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        void navigator.clipboard.writeText(
                          `${window.location.origin}${base}${feed.path}`,
                        )
                      }
                      title="Copy the full URL"
                    >
                      <Copy />
                    </Button>
                    <Button size="sm" variant="ghost" asChild>
                      <a href={`${base}${feed.path}`} target="_blank" rel="noreferrer">
                        <ExternalLink />
                      </a>
                    </Button>
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
              <Link2 className="size-4" />
              How a consumer authenticates
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-muted-foreground">
            <p>
              Identity comes from Keycloak in a deployment, or an{" "}
              <span className="num">X-Demo-User</span> header for local work. Both resolve to the
              same entitlements, so the enforcement below never learns which door a caller used.
            </p>
            <p>
              Entitlements are applied by a row-level policy on the canonical project table, which
              every metric view reaches through. One policy scopes the whole metric and mart layer
              — including anything a workbook pulls.
            </p>
            <p>
              There is no per-feed token, and that is the design: a token-secured side channel is a
              second authorisation model to keep in step with the first.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {health.data?.status === "healthy" ? (
                <CheckCircle2 className="size-4 text-ok" />
              ) : (
                <XCircle className="size-4 text-bad" />
              )}
              What this screen is not
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">No inbound workbook sync.</span>{" "}
              Pulling a BI tool&apos;s workbooks and published data sources into this platform
              would import their calculation logic with them, and the whole point of the mart layer
              is that the calculation happens once, here.
            </p>
            <p>
              <span className="font-medium text-foreground">No private outbound feed tokens.</span>{" "}
              A feed with its own token and its own shape is a second definition surface that
              nobody diffs against the catalogue. Consumers use the governed endpoints above, under
              a real identity.
            </p>
            <p>
              If a consumer genuinely needs a different shape, the answer is a new mart with a
              registered definition — a reviewable change in version control, not a URL someone
              minted in a console.
            </p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Badge variant="outline">read-only</Badge>
              <Badge variant="outline">entitlement-scoped</Badge>
              <Badge variant="outline">provenance attached</Badge>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
