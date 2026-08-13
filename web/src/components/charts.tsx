/**
 * Transfer & Conversion Intelligence Platform :: chart building blocks.
 *
 * Every mark reads a role token from `styles.css`. No component here holds a
 * colour literal, so no panel can hold a private palette — the argument the
 * metric layer makes about KPI definitions, applied to colour.
 *
 * Three scales, chosen by what the data *is*, not by taste:
 *
 *   categorical  cohorts with no order — transfer type, site, portfolio
 *   ordinal      forecast horizons, which are ordered, so a single-hue ramp
 *   diverging    schedule drift, where the sign is the entire point
 *
 * The status scale (`ok`/`warn`/`bad`) is reserved and never doubles as a series
 * colour, so green means one thing everywhere in the console.
 */
import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const CATEGORICAL = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const;

export const ORDINAL = [
  "var(--ordinal-1)",
  "var(--ordinal-2)",
  "var(--ordinal-3)",
  "var(--ordinal-4)",
] as const;

export const categorical = (index: number) => CATEGORICAL[index % CATEGORICAL.length]!;
export const ordinal = (index: number) => ORDINAL[Math.min(index, ORDINAL.length - 1)]!;
export const diverging = (value: number) =>
  value > 0 ? "var(--diverging-pos)" : "var(--diverging-neg)";

const axis = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      <div className="mb-1 font-medium">{label}</div>
      {payload.map((entry, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ background: entry.color }}
            aria-hidden
          />
          <span className="text-muted-foreground">{entry.name}</span>
          <span className="num ml-auto">
            {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Frame({ height = 240, children }: { height?: number; children: React.ReactElement }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

// ---- Trend -----------------------------------------------------------------
export function TrendChart({
  data,
  x,
  series,
  unit,
  height,
}: {
  data: Record<string, unknown>[];
  x: string;
  series: { key: string; name: string }[];
  unit?: string;
  height?: number;
}) {
  return (
    <Frame height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey={x} {...axis} />
        <YAxis {...axis} width={44} />
        <Tooltip content={<ChartTooltip unit={unit} />} />
        {series.map((entry, index) => (
          <Line
            key={entry.key}
            type="monotone"
            dataKey={entry.key}
            name={entry.name}
            stroke={categorical(index)}
            strokeWidth={2}
            dot={{ r: 2.5 }}
            activeDot={{ r: 4 }}
            connectNulls
          />
        ))}
      </LineChart>
    </Frame>
  );
}

// ---- Categorical bars ------------------------------------------------------
export function CohortBars({
  data,
  x,
  y,
  name,
  unit,
  height,
}: {
  data: Record<string, unknown>[];
  x: string;
  y: string;
  name: string;
  unit?: string;
  height?: number;
}) {
  return (
    <Frame height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey={x} {...axis} interval={0} angle={-15} textAnchor="end" height={48} />
        <YAxis {...axis} width={44} />
        <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ fill: "var(--muted)" }} />
        <Bar dataKey={y} name={name} radius={[3, 3, 0, 0]}>
          {data.map((_row, index) => (
            <Cell key={index} fill={categorical(index)} />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

// ---- Ordinal bars (forecast horizons) --------------------------------------
export function HorizonBars({
  data,
  x,
  y,
  name,
  unit,
  height,
}: {
  data: Record<string, unknown>[];
  x: string;
  y: string;
  name: string;
  unit?: string;
  height?: number;
}) {
  return (
    <Frame height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey={x} {...axis} />
        <YAxis {...axis} width={44} />
        <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ fill: "var(--muted)" }} />
        <Bar dataKey={y} name={name} radius={[3, 3, 0, 0]}>
          {data.map((_row, index) => (
            <Cell key={index} fill={ordinal(index)} />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

// ---- Diverging bars (schedule drift) ---------------------------------------
export function DriftBars({
  data,
  x,
  y,
  name,
  height,
}: {
  data: Record<string, unknown>[];
  x: string;
  y: string;
  name: string;
  height?: number;
}) {
  return (
    <Frame height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey={x} {...axis} interval={0} angle={-15} textAnchor="end" height={48} />
        <YAxis {...axis} width={44} />
        <Tooltip content={<ChartTooltip unit="d" />} cursor={{ fill: "var(--muted)" }} />
        {/* Zero is the frozen baseline. Without the line, "ahead" and "behind"
            are a colour convention the reader has to already know. */}
        <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeWidth={1} />
        <Bar dataKey={y} name={name} radius={[3, 3, 0, 0]}>
          {data.map((row, index) => (
            <Cell key={index} fill={diverging(Number(row[y] ?? 0))} />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

// ---- Box plot --------------------------------------------------------------
/**
 * Hand-built, because the spread is the point and a bar of the median throws
 * away the tail that the P90 exists to show. Recharts has no box plot, and one
 * SVG component is a smaller commitment than a second charting dependency.
 */
export function BoxPlot({
  rows,
  height = 260,
}: {
  rows: {
    cohort: string;
    n: number;
    min_days: number | null;
    p25: number | null;
    p50: number | null;
    p75: number | null;
    p90: number | null;
    max_days: number | null;
  }[];
  height?: number;
}) {
  const values = rows.flatMap((row) =>
    [row.min_days, row.p25, row.p50, row.p75, row.p90, row.max_days].filter(
      (value): value is number => value !== null,
    ),
  );
  if (values.length === 0) return null;

  const max = Math.max(...values);
  const min = Math.min(0, Math.min(...values));
  const padTop = 20;
  const padBottom = 48;
  const padLeft = 48;
  const padRight = 24;
  const minBandWidth = 110;
  const viewWidth = Math.max(padLeft + padRight + rows.length * minBandWidth, 420);
  const plotWidth = viewWidth - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const scale = (value: number) =>
    padTop + plotHeight - ((value - min) / (max - min || 1)) * plotHeight;

  const bandWidth = plotWidth / rows.length;
  const boxWidth = Math.min(60, bandWidth * 0.58);

  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${height}`}
      className="block h-auto w-full max-w-none"
      style={{ minWidth: viewWidth }}
      role="img"
      aria-label="Cycle-time distribution by cohort"
    >
      {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
        const value = min + (max - min) * fraction;
        return (
          <g key={fraction}>
            <line
              x1={padLeft}
              x2={viewWidth - padRight}
              y1={scale(value)}
              y2={scale(value)}
              stroke="var(--grid)"
              strokeDasharray="3 3"
            />
            <text
              x={padLeft - 8}
              y={scale(value) + 4}
              textAnchor="end"
              fontSize="11"
              fill="var(--muted-foreground)"
            >
              {Math.round(value)}
            </text>
          </g>
        );
      })}

      {rows.map((row, index) => {
        const centre = padLeft + (index + 0.5) * bandWidth;
        const x = centre - boxWidth / 2;
        const p90Inset = Math.min(12, boxWidth * 0.2);
        const colour = categorical(index);
        const box = {
          top: row.p75 === null ? null : scale(row.p75),
          bottom: row.p25 === null ? null : scale(row.p25),
        };
        return (
          <g key={row.cohort} data-centre={centre}>
            {row.min_days !== null && row.max_days !== null ? (
              <line
                x1={centre}
                x2={centre}
                y1={scale(row.min_days)}
                y2={scale(row.max_days)}
                stroke={colour}
                strokeWidth={1}
              />
            ) : null}
            {box.top !== null && box.bottom !== null ? (
              <rect
                x={x}
                y={box.top}
                width={boxWidth}
                height={Math.max(box.bottom - box.top, 1)}
                fill={colour}
                fillOpacity={0.25}
                stroke={colour}
                strokeWidth={1.5}
                rx={2}
              />
            ) : null}
            {row.p50 !== null ? (
              <line
                x1={x}
                x2={x + boxWidth}
                y1={scale(row.p50)}
                y2={scale(row.p50)}
                stroke={colour}
                strokeWidth={2.5}
              />
            ) : null}
            {row.p90 !== null ? (
              <line
                x1={x + p90Inset}
                x2={x + boxWidth - p90Inset}
                y1={scale(row.p90)}
                y2={scale(row.p90)}
                stroke={colour}
                strokeWidth={1}
                strokeDasharray="4 2"
              />
            ) : null}
            <text
              x={centre}
              y={height - 24}
              textAnchor="middle"
              fontSize="11"
              fill="var(--foreground)"
            >
              {row.cohort}
            </text>
            <text
              x={centre}
              y={height - 10}
              textAnchor="middle"
              fontSize="10"
              fill="var(--muted-foreground)"
            >
              n={row.n}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
