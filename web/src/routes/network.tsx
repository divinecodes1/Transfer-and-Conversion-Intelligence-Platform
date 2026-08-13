/**
 * Transfer & Conversion Intelligence Platform :: transfer network intelligence.
 *
 * The portfolio screens aggregate by fiscal year, transfer type and complexity.
 * None of those answer the question a manufacturing network actually asks, which
 * is about a *lane*: how does Villach → Kulim behave, and does it behave like
 * Dresden → Kulim? A site pair is where qualification capacity, tooling and the
 * receiving factory's experience all live, so it is where the differences are.
 *
 * Every figure here is an already-registered metric re-grained onto the lane.
 * There is no lane-specific definition of "on time" — that is the point of a
 * semantic layer, and sql/13_readiness_network.sql is where the GROUP BY lives.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Waypoints } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { fmtDays, fmtNumber, fmtPercent, networkQuery, type LaneRow } from "@/lib/marts";

/** Lanes carrying a single transfer are noise on a network view, not signal. */
const MIN_TRANSFERS = 3;

function laneKey(lane: LaneRow) {
  return `${lane.source_site}->${lane.target_site}`;
}

export function NetworkScreen() {
  const query = useQuery(networkQuery(MIN_TRANSFERS));
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);

  const lanes = query.data?.lanes ?? [];
  const sites = query.data?.sites ?? [];
  const selected = lanes.find((lane) => laneKey(lane) === selectedKey) ?? lanes[0];

  // Inbound and outbound arrive as separate rows; pairing them for display is
  // presentation, not calculation — the totals themselves are summed in SQL.
  const bySite = React.useMemo(() => {
    const map = new Map<string, { inbound: number; outbound: number; active: number }>();
    for (const row of sites) {
      const entry = map.get(row.site) ?? { inbound: 0, outbound: 0, active: 0 };
      if (row.direction === "INBOUND") entry.inbound = row.transfers;
      else entry.outbound = row.transfers;
      entry.active += row.active_transfers;
      map.set(row.site, entry);
    }
    return [...map.entries()]
      .map(([site, counts]) => ({ site, ...counts }))
      .sort((a, b) => b.inbound + b.outbound - (a.inbound + a.outbound));
  }, [sites]);

  const busiest = lanes[0];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Transfer network"
        description="Every source-to-target lane in the portfolio, and how each one performs. Lanes carrying fewer than three transfers are omitted — a median over one project is not a median."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          label="Active lanes"
          value={fmtNumber(lanes.length)}
          hint={`${fmtNumber(bySite.length)} sites connected`}
          loading={query.isLoading}
        />
        <KpiTile
          label="Busiest lane"
          value={busiest ? `${busiest.source_site} → ${busiest.target_site}` : "—"}
          hint={busiest ? `${fmtNumber(busiest.total_transfers)} transfers` : undefined}
          loading={query.isLoading}
        />
        <KpiTile
          label="Transfers on lanes"
          value={fmtNumber(lanes.reduce((sum, lane) => sum + lane.total_transfers, 0))}
          hint="Across every lane shown"
          loading={query.isLoading}
        />
        <KpiTile
          label="In flight"
          value={fmtNumber(lanes.reduce((sum, lane) => sum + lane.active_transfers, 0))}
          hint="Active transfers on these lanes"
          loading={query.isLoading}
        />
      </div>

      {selected ? (
        <Panel
          title={`${selected.source_site} → ${selected.target_site}`}
          description="Lane performance. Select any lane below to change this view."
          envelope={query.data}
          actions={
            <Badge variant="muted">
              <Waypoints className="mr-1 size-3.5" />
              lane detail
            </Badge>
          }
        >
          <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <LaneStat label="Active transfers" value={fmtNumber(selected.active_transfers)} />
            <LaneStat label="Completed transfers" value={fmtNumber(selected.completed_transfers)} />
            <LaneStat label="Median lead time" value={`${fmtNumber(selected.median_lead_time_days)} d`} />
            <LaneStat label="On-time completion" value={fmtPercent(selected.on_time_rate)} />
            <LaneStat label="Average readiness" value={fmtPercent(selected.avg_readiness_pct)} />
            <LaneStat label="Median schedule drift" value={fmtDays(selected.median_schedule_deviation_days)} />
            <LaneStat
              label="Most common bottleneck"
              value={selected.bottleneck_stage ?? "—"}
              hint={
                selected.bottleneck_median_days !== null
                  ? `median ${fmtNumber(selected.bottleneck_median_days)} d in stage`
                  : undefined
              }
            />
            <LaneStat label="Late transfers" value={fmtNumber(selected.late_transfers)} />
            <LaneStat label="Planned" value={fmtNumber(selected.planned_transfers)} />
          </div>
        </Panel>
      ) : null}

      <Panel
        title="Lanes"
        description="Ranked by volume. The bottleneck column is the lifecycle stage that consumes the most time on that lane."
        envelope={query.data}
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={lanes.length === 0}
          emptyMessage="No lane in this scope carries enough transfers to summarise."
          onRetry={() => void query.refetch()}
        >
          <Table maxHeight="max-h-[calc(100vh-22rem)]">
            <TableHeader>
              <TableRow>
                <TableHead>Lane</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Active</TableHead>
                <TableHead className="text-right">Median lead</TableHead>
                <TableHead className="text-right">On time</TableHead>
                <TableHead className="text-right">Readiness</TableHead>
                <TableHead>Bottleneck</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lanes.map((lane) => (
                <TableRow
                  key={laneKey(lane)}
                  data-state={laneKey(lane) === laneKey(selected!) ? "selected" : undefined}
                >
                  <TableCell className="font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      {lane.source_site}
                      <ArrowRight className="size-3.5 text-muted-foreground" />
                      {lane.target_site}
                    </span>
                  </TableCell>
                  <TableCell className="num text-right">{fmtNumber(lane.total_transfers)}</TableCell>
                  <TableCell className="num text-right text-muted-foreground">
                    {fmtNumber(lane.active_transfers)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {fmtNumber(lane.median_lead_time_days)} d
                  </TableCell>
                  <TableCell className="num text-right">{fmtPercent(lane.on_time_rate)}</TableCell>
                  <TableCell className="num text-right">
                    {fmtPercent(lane.avg_readiness_pct)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {lane.bottleneck_stage ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedKey(laneKey(lane))}
                    >
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </Panel>

      <Panel
        title="Sites"
        description="Inbound and outbound transfer counts per site, summed across every lane."
        envelope={query.data}
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={bySite.length === 0}
          onRetry={() => void query.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Site</TableHead>
                <TableHead className="text-right">Inbound</TableHead>
                <TableHead className="text-right">Outbound</TableHead>
                <TableHead className="text-right">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bySite.map((row) => (
                <TableRow key={row.site}>
                  <TableCell className="font-medium">{row.site}</TableCell>
                  <TableCell className="num text-right">{fmtNumber(row.inbound)}</TableCell>
                  <TableCell className="num text-right">{fmtNumber(row.outbound)}</TableCell>
                  <TableCell className="num text-right font-semibold">
                    {fmtNumber(row.inbound + row.outbound)}
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

function LaneStat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="num mt-0.5 text-lg font-semibold">{value}</div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}
