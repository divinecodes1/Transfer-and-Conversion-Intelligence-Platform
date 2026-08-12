/**
 * Transfer & Conversion Intelligence Platform :: the pieces every panel is built from.
 *
 * `Provenance` is the important one. Every panel in this console prints the
 * definition, population, filters and data vintage that produced it, rendered
 * from the envelope the API sent rather than from anything written here —
 * `tests/web_checks.py` asserts no registered definition text appears anywhere
 * under `web/src`.
 *
 * That footnote is the deliberate answer to "he knows which filters to set,
 * future users won't". The chart explains its own scope instead of relying on
 * someone remembering it.
 */
import * as React from "react";
import { AlertTriangle, Info, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtNumber, type Envelope, type MetricDefinition } from "@/lib/marts";

// ---- Page furniture --------------------------------------------------------
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-0.5 max-w-3xl text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </div>
  );
}

// ---- Loading, empty and error states --------------------------------------
export function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyMessage = "No rows in this scope.",
  onRetry,
  rows = 4,
  children,
}: {
  isLoading: boolean;
  error?: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  onRetry?: () => void;
  rows?: number;
  children: React.ReactNode;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-live="polite">
        {Array.from({ length: rows }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="flex flex-col items-start gap-2 rounded-md border border-bad/25 bg-bad/5 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-bad">
          <AlertTriangle className="size-4" />
          Could not load this panel
        </div>
        {/* The API's own message, verbatim. A generic "something went wrong"
            turns a 403 you can fix into a mystery. */}
        <p className="text-xs text-muted-foreground">{message}</p>
        {onRetry ? (
          <Button size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  return <>{children}</>;
}

export function InlineSpinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      {label}
    </span>
  );
}

// ---- Provenance ------------------------------------------------------------
function definitionLine(metric: MetricDefinition) {
  const parts = [`${metric.business_name} = ${metric.definition}`];
  if (metric.population) parts.push(`population: ${metric.population}`);
  if (metric.exclusions) parts.push(`excludes: ${metric.exclusions}`);
  if (metric.version) parts.push(`v${metric.version}`);
  return parts.join(" · ");
}

export function Provenance({
  envelope,
  className,
}: {
  envelope: Envelope | undefined;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  if (!envelope) return null;

  const applied = Object.entries(envelope.filters_applied ?? {});
  const metrics = envelope.metrics ?? [];

  return (
    <div className={cn("mt-3 border-t border-border pt-2 text-xs", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="inline-flex items-center gap-1 hover:text-foreground"
          aria-expanded={open}
        >
          <Info className="size-3.5" />
          {metrics.length === 1
            ? metrics[0]!.business_name
            : `${metrics.length} governed metrics`}
        </button>

        <span>
          Scope:{" "}
          {applied.length === 0
            ? "whole portfolio"
            : applied.map(([key, value]) => `${key.replace(/_/g, " ")} = ${value}`).join(", ")}
        </span>

        {envelope.n_projects !== undefined ? (
          <span className="num">n = {fmtNumber(envelope.n_projects)}</span>
        ) : null}

        {envelope.data_as_of ? (
          <span>
            Data as of <span className="num">{String(envelope.data_as_of).slice(0, 10)}</span>
          </span>
        ) : null}
      </div>

      {open ? (
        <ul className="mt-2 space-y-1 text-muted-foreground">
          {metrics.map((metric) => (
            <li key={metric.metric_code}>
              <span className="num text-foreground">{metric.metric_code}</span>{" "}
              {definitionLine(metric)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** A panel with its provenance footnote already attached. */
export function Panel({
  title,
  description,
  envelope,
  actions,
  className,
  children,
}: {
  title: string;
  description?: string;
  envelope?: Envelope;
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>{title}</CardTitle>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </CardHeader>
      <CardContent>
        {children}
        <Provenance envelope={envelope} />
      </CardContent>
    </Card>
  );
}

// ---- KPI tile --------------------------------------------------------------
export function KpiTile({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  loading,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: "neutral" | "ok" | "warn" | "bad";
  loading?: boolean;
}) {
  const toneClass = {
    neutral: "text-foreground",
    ok: "text-ok",
    warn: "text-warn",
    bad: "text-bad",
  }[tone];

  return (
    <Card className="p-4">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <div className={cn("num mt-1 text-2xl font-semibold tabular-nums", toneClass)}>
          {value}
          {unit ? <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span> : null}
        </div>
      )}
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}

// ---- Health band -----------------------------------------------------------
const HEALTH_VARIANT = {
  ON_TRACK: "ok",
  AT_RISK: "warn",
  LATE: "bad",
  UNKNOWN: "muted",
} as const;

const HEALTH_LABEL = {
  ON_TRACK: "On track",
  AT_RISK: "At risk",
  LATE: "Late",
  UNKNOWN: "Unknown",
} as const;

/**
 * The health band, banded in SQL and only *rendered* here.
 *
 * Always a labelled dot, never colour alone — the status scale has to survive a
 * reader who cannot distinguish the hues, and a legend that only exists in the
 * palette is not a legend.
 */
export function HealthBadge({ health }: { health: keyof typeof HEALTH_VARIANT }) {
  return (
    <Badge dot variant={HEALTH_VARIANT[health] ?? "muted"}>
      {HEALTH_LABEL[health] ?? health}
    </Badge>
  );
}
