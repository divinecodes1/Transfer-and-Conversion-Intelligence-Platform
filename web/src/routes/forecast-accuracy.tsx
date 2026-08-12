/**
 * Transfer & Conversion Intelligence Platform :: forecast accuracy by horizon.
 *
 * The screen exists to prevent one specific self-deception. "How accurate was
 * our latest forecast?" makes any organisation look excellent, because a
 * forecast revised three days before completion is nearly always right.
 * Bucketing by how far *before* the finish the forecast was made is what exposes
 * that, and the preserved snapshot history is what makes it computable at all.
 *
 * The horizon ramp is single-hue on purpose: the buckets are ordered, and a
 * categorical palette would imply they are five unrelated things.
 */
import { useQuery } from "@tanstack/react-query";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { HorizonBars } from "@/components/charts";
import { KpiTile, PageHeader, Panel, QueryState } from "@/components/panels";
import { useFilters } from "@/lib/app-state";
import { accuracyQuery, fmtDays, fmtNumber, fmtPercent } from "@/lib/marts";

export function ForecastAccuracyScreen() {
  const { filters } = useFilters();
  const query = useQuery(accuracyQuery(filters));
  const rows = query.data?.series ?? [];

  const nearest = rows[0];
  const furthest = rows[rows.length - 1];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Forecast accuracy"
        description="Forecast error bucketed by how far before completion the forecast was made — not by how good the last forecast turned out to be."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          label="Error inside 30 days"
          value={fmtNumber(nearest?.median_abs_error)}
          unit="d"
          hint="Median absolute error"
          tone="ok"
          loading={query.isLoading}
        />
        <KpiTile
          label="Error 90+ days out"
          value={fmtNumber(furthest?.median_abs_error)}
          unit="d"
          hint="Median absolute error"
          tone="warn"
          loading={query.isLoading}
        />
        <KpiTile
          label="Hit rate inside 30 days"
          value={fmtPercent(nearest?.within_14_days_pct)}
          hint="Within 14 days of the actual finish"
          loading={query.isLoading}
        />
        <KpiTile
          label="Hit rate 90+ days out"
          value={fmtPercent(furthest?.within_14_days_pct)}
          hint="Within 14 days of the actual finish"
          loading={query.isLoading}
        />
      </div>

      <Panel
        title="Median absolute error by horizon"
        description="How wrong a forecast typically was, given how far ahead it was made."
        envelope={query.data}
      >
        <QueryState
          isLoading={query.isLoading}
          error={query.error}
          isEmpty={rows.length === 0}
          onRetry={() => void query.refetch()}
        >
          <HorizonBars
            data={rows as unknown as Record<string, unknown>[]}
            x="horizon_bucket"
            y="median_abs_error"
            name="Median absolute error"
            unit=" d"
          />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Horizon</TableHead>
                <TableHead>n</TableHead>
                <TableHead>Median error</TableHead>
                <TableHead>Bias</TableHead>
                <TableHead>Median abs. error</TableHead>
                <TableHead>P90 abs. error</TableHead>
                <TableHead>Within 14 days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.horizon_bucket}>
                  <TableCell className="num">{row.horizon_bucket} days out</TableCell>
                  <TableCell className="num">{fmtNumber(row.n)}</TableCell>
                  <TableCell className="num">{fmtDays(row.median_error)}</TableCell>
                  <TableCell className="num">{fmtDays(row.bias)}</TableCell>
                  <TableCell className="num font-medium">
                    {fmtNumber(row.median_abs_error)} d
                  </TableCell>
                  <TableCell className="num">{fmtNumber(row.p90_abs_error)} d</TableCell>
                  <TableCell className="num">{fmtPercent(row.within_14_days_pct)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {query.data?.note ? (
            <p className="mt-3 text-xs text-muted-foreground">{query.data.note}</p>
          ) : null}
        </QueryState>
      </Panel>

      <Panel
        title="Reading this panel"
        description="What the numbers above are, and are not."
      >
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">Bias</span> is the signed average
            error. A positive bias means projects finished later than forecast — the forecast was
            optimistic.
          </li>
          <li>
            <span className="font-medium text-foreground">Median absolute error</span> ignores the
            sign and answers &ldquo;how far out were we, typically?&rdquo;
          </li>
          <li>
            <span className="font-medium text-foreground">Within 14 days</span> is the share close
            enough to plan a handover around. The threshold is defined once in the metric layer,
            so no screen can quietly move it to make a chart look better.
          </li>
          <li>
            Accuracy improving as the horizon shortens is expected. The useful question is whether
            the long-horizon buckets are good enough to commit a customer date to.
          </li>
        </ul>
      </Panel>
    </div>
  );
}
