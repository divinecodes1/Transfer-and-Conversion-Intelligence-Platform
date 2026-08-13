/**
 * Transfer & Conversion Intelligence Platform :: typed queries over the governed mart endpoints.
 *
 * One `queryOptions` per panel, and one filter contract shared by all of them —
 * so a screen cannot accidentally ask a different question than the footnote
 * under it claims. Every response type includes the provenance envelope, and the
 * `<Provenance>` component renders it from the response rather than from
 * anything written in the browser.
 */
import { queryOptions } from "@tanstack/react-query";
import { get } from "./api";

/** The filter contract. Identical to the API's, and to the assistant's. */
export type Filters = {
  fiscal_year?: number | null;
  site?: string | null;
  transfer_type?: string | null;
  portfolio?: string | null;
  complexity?: string | null;
  /** What is being moved. Bound on the catalogue CODE, never the display name. */
  product_line?: string | null;
  /** Which end market buys it. Also a code. */
  application_segment?: string | null;
};

export const emptyFilters: Filters = {};

/** Just the set filters, in a stable key order — also the query-cache key. */
export function activeFilters(filters: Filters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const key of [
    "fiscal_year",
    "site",
    "transfer_type",
    "portfolio",
    "complexity",
    "product_line",
    "application_segment",
  ] as const) {
    const value = filters[key];
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

export function filterCount(filters: Filters) {
  return Object.keys(activeFilters(filters)).length;
}

// ---- The provenance envelope ----------------------------------------------
export type MetricDefinition = {
  metric_code: string;
  business_name: string;
  definition: string;
  grain: string | null;
  unit: string | null;
  population: string | null;
  exclusions: string | null;
  owner: string | null;
  version: string | null;
  effective_from: string | null;
  endpoint?: string | null;
};

export type Envelope = {
  metrics: MetricDefinition[];
  filters_applied: Record<string, string | number>;
  data_as_of: string | null;
  n_projects?: number;
};

// ---- Payloads --------------------------------------------------------------
export type PortfolioKpis = {
  throughput: number | null;
  wip: number | null;
  median_cycle_time: number | null;
  p90_cycle_time: number | null;
  on_time_rate: number | null;
  replan_rate: number | null;
  median_wip_age: number | null;
  median_schedule_deviation: number | null;
  delayed_count: number | null;
  total_projects: number | null;
};

export type TrendRow = {
  fiscal_year: number;
  throughput: number;
  median_cycle_time: number | null;
  on_time_rate: number | null;
  replan_rate: number | null;
};

export type DistributionRow = {
  cohort: string;
  n: number;
  min_days: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p90: number | null;
  max_days: number | null;
  iqr: number | null;
};

export type AccuracyRow = {
  horizon_bucket: string;
  horizon_days: number;
  n: number;
  median_error: number | null;
  bias: number | null;
  median_abs_error: number | null;
  p90_abs_error: number | null;
  within_14_days_pct: number | null;
};

export type ProjectRow = {
  project_key: number;
  project_id: string;
  project_name: string | null;
  transfer_type: string | null;
  complexity_class: string | null;
  portfolio: string | null;
  // Code and display name arrive together from the catalogue join, so a table
  // cell can render the name without the browser holding a lookup that could
  // drift from the codes it is filtering on.
  product_line: string | null;
  product_name: string | null;
  application_segment: string | null;
  application_name: string | null;
  source_site: string | null;
  target_site: string | null;
  status: string;
  actual_start: string | null;
  actual_finish: string | null;
  baseline_start: string | null;
  baseline_finish: string | null;
  latest_start: string | null;
  latest_finish: string | null;
  latest_forecast_finish: string | null;
  actual_cycle_time_days: number | null;
  schedule_deviation_days: number | null;
  completion_variance_days: number | null;
  on_time: boolean | null;
  revision_count: number | null;
  replan_count: number | null;
  was_replanned: boolean | null;
  last_revised_at: string | null;
  wip_age_days: number | null;
  completion_fiscal_year: number | null;
  start_fiscal_year: number | null;
  health: "ON_TRACK" | "AT_RISK" | "LATE" | "UNKNOWN";
};

export type ScheduleRevision = {
  revision_id: number;
  revision_timestamp: string;
  revision_reason: string;
  planned_start: string | null;
  planned_finish: string | null;
  forecast_finish: string | null;
  is_baseline: boolean;
};

export type ProjectDetail = {
  data_as_of: string | null;
  project: ProjectRow & Record<string, unknown>;
  schedule_revisions: ScheduleRevision[];
  milestones: {
    milestone_code: string;
    milestone_name: string;
    sequence_no: number;
    planned_date: string | null;
    actual_date: string | null;
    event_status: string;
  }[];
  snapshots: {
    snapshot_date: string;
    status: string;
    forecast_finish: string | null;
  }[];
};

// ---- Queries ---------------------------------------------------------------
export const kpisQuery = (filters: Filters) =>
  queryOptions({
    queryKey: ["kpis", activeFilters(filters)],
    queryFn: ({ signal }) =>
      get<Envelope & { kpis: PortfolioKpis }>("/mart/kpis", activeFilters(filters), signal),
  });

export const trendQuery = (filters: Filters) => {
  // The trend is a time series, so it is never scoped to a single fiscal year:
  // a trend line with one point on it is a number wearing a chart's clothes.
  const { fiscal_year: _drop, ...rest } = activeFilters(filters);
  return queryOptions({
    queryKey: ["trend", rest],
    queryFn: ({ signal }) => get<Envelope & { series: TrendRow[] }>("/mart/trend", rest, signal),
  });
};

export const distributionQuery = (filters: Filters, groupBy: string) =>
  queryOptions({
    queryKey: ["distribution", activeFilters(filters), groupBy],
    queryFn: ({ signal }) =>
      get<Envelope & { group_by: string; series: DistributionRow[] }>(
        "/mart/distribution",
        { ...activeFilters(filters), group_by: groupBy },
        signal,
      ),
  });

export const accuracyQuery = (filters: Filters) => {
  const { fiscal_year: _drop, ...rest } = activeFilters(filters);
  return queryOptions({
    queryKey: ["accuracy", rest],
    queryFn: ({ signal }) =>
      get<Envelope & { note: string; series: AccuracyRow[] }>("/mart/accuracy", rest, signal),
  });
};

export type ProjectListOptions = {
  search?: string;
  status?: string;
  health?: string;
  sort_by?: string;
  descending?: boolean;
  limit?: number;
};

export const projectsQuery = (filters: Filters, options: ProjectListOptions = {}) =>
  queryOptions({
    queryKey: ["projects", activeFilters(filters), options],
    queryFn: ({ signal }) =>
      get<Envelope & { total_matching: number; projects: ProjectRow[] }>(
        "/mart/projects",
        { ...activeFilters(filters), limit: 500, ...options },
        signal,
      ),
  });

export const projectDetailQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => get<ProjectDetail>(`/projects/${projectId}`, undefined, signal),
  });

/**
 * A filter option: the value that binds, and the label a human reads.
 *
 * They differ only for the product and application taxonomy, where the filter
 * carries a stable code and the dropdown shows the catalogue's display name.
 * Both come from the API — deriving one from the other in the browser would
 * make the console a second naming authority.
 */
export type FilterOption = { value: string; label: string };

export const filterOptionsQuery = () =>
  queryOptions({
    queryKey: ["filter-options"],
    queryFn: ({ signal }) =>
      get<{ data_as_of: string | null; options: Record<string, FilterOption[]> }>(
        "/mart/filter-options",
        undefined,
        signal,
      ),
    staleTime: 5 * 60 * 1000,
  });

export const catalogueQuery = () =>
  queryOptions({
    queryKey: ["catalogue"],
    queryFn: ({ signal }) => get<{ metrics: MetricDefinition[] }>("/catalogue", undefined, signal),
    staleTime: 5 * 60 * 1000,
  });

export const whoamiQuery = () =>
  queryOptions({
    queryKey: ["whoami"],
    queryFn: ({ signal }) =>
      get<{
        username: string;
        roles: string[];
        portfolios: string[];
        sites: string[];
        source: string;
      }>("/whoami", undefined, signal),
    staleTime: 60 * 1000,
  });

export const healthQuery = () =>
  queryOptions({
    queryKey: ["health"],
    queryFn: ({ signal }) =>
      get<{ status: string; projects: number; data_as_of: string | null }>(
        "/health",
        undefined,
        signal,
      ),
    staleTime: 30 * 1000,
  });

export const stageCycleTimeQuery = () =>
  queryOptions({
    queryKey: ["stage-cycle-time"],
    queryFn: ({ signal }) =>
      get<Envelope & { series: { from_stage: string; to_stage: string; n: number; median: number | null; p90: number | null }[] }>(
        "/metrics/stage-cycle-time",
        undefined,
        signal,
      ),
  });

export const scheduleDriftQuery = (filters: Filters, groupBy = "transfer_type") =>
  queryOptions({
    queryKey: ["schedule-drift", activeFilters(filters), groupBy],
    queryFn: ({ signal }) =>
      get<
        Envelope & {
          group_by: string;
          series: {
            group_value: string;
            n: number;
            min_days: number | null;
            p25: number | null;
            median: number | null;
            p75: number | null;
            p90: number | null;
            max_days: number | null;
          }[];
        }
      >(
        "/metrics/schedule-drift",
        { group_by: groupBy, ...activeFilters(filters) },
        signal,
      ),
  });

// ---- Readiness, network and similarity -------------------------------------
// The bands and the weights are read from the response, never declared here.
// A `READY` string in the browser is a label; the boundary that produced it
// lives in sql/13_readiness_network.sql, which is what lets tests/web_checks.py
// keep asserting the console re-derives no threshold.
export type ReadinessBand = "READY" | "AT_RISK" | "NOT_READY";

export type ReadinessRow = {
  project_key: number;
  project_id: string;
  project_name: string | null;
  transfer_type: string | null;
  complexity_class: string | null;
  portfolio: string | null;
  source_site: string | null;
  target_site: string | null;
  status: string;
  health: ProjectRow["health"] | null;
  schedule_deviation_days: number | null;
  readiness_pct: number | null;
  readiness_band: ReadinessBand;
  dimensions_assessed: number | null;
  limiting_dimension: string | null;
  limiting_dimension_name: string | null;
  limiting_score: number | null;
  newest_assessment: string | null;
  assessment_age_days: number | null;
};

export type ReadinessSummary = {
  projects: number | null;
  avg_readiness_pct: number | null;
  ready_count: number | null;
  at_risk_count: number | null;
  not_ready_count: number | null;
  avg_assessment_age_days: number | null;
};

export type ReadinessDimensionRow = {
  dimension_code: string;
  dimension_name: string;
  weight_pct: number;
  sequence_no: number;
  avg_score_pct: number | null;
  min_score_pct: number | null;
  projects: number | null;
  below_70: number | null;
};

export type LaneRow = {
  source_site: string;
  target_site: string;
  total_transfers: number;
  active_transfers: number;
  completed_transfers: number;
  planned_transfers: number;
  median_lead_time_days: number | null;
  on_time_rate: number | null;
  median_schedule_deviation_days: number | null;
  avg_readiness_pct: number | null;
  late_transfers: number | null;
  bottleneck_stage: string | null;
  bottleneck_median_days: number | null;
};

export type SiteFlowRow = {
  site: string;
  direction: "INBOUND" | "OUTBOUND";
  transfers: number;
  active_transfers: number;
};

export type SimilarRow = {
  similar_project_id: string;
  similar_project_name: string | null;
  similarity_pct: number;
  match_transfer_type: boolean;
  match_complexity: boolean;
  match_portfolio: boolean;
  match_target_site: boolean;
  match_source_site: boolean;
  transfer_type: string | null;
  complexity_class: string | null;
  source_site: string | null;
  target_site: string | null;
  actual_cycle_time_days: number | null;
  completion_variance_days: number | null;
  on_time: boolean | null;
  health: ProjectRow["health"] | null;
  completion_fiscal_year: number | null;
};

/** Readiness has no fiscal-year dimension: it only describes unfinished work. */
function readinessFilters(filters: Filters) {
  const { fiscal_year: _drop, ...rest } = activeFilters(filters);
  return rest;
}

export const readinessQuery = (filters: Filters, options: { band?: string } = {}) => {
  const params = { ...readinessFilters(filters), ...options };
  return queryOptions({
    queryKey: ["readiness", params],
    queryFn: ({ signal }) =>
      get<Envelope & { summary: ReadinessSummary; projects: ReadinessRow[] }>(
        "/readiness",
        params,
        signal,
      ),
  });
};

export const readinessDimensionsQuery = (filters: Filters) => {
  const params = readinessFilters(filters);
  return queryOptions({
    queryKey: ["readiness-dimensions", params],
    queryFn: ({ signal }) =>
      get<Envelope & { dimensions: ReadinessDimensionRow[] }>(
        "/readiness/dimensions",
        params,
        signal,
      ),
  });
};

export const projectReadinessQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["project-readiness", projectId],
    queryFn: ({ signal }) =>
      get<
        Envelope & {
          assessed: boolean;
          reason?: string;
          overall: ReadinessRow | null;
          dimensions: {
            dimension_code: string;
            dimension_name: string;
            weight_pct: number;
            sequence_no: number;
            score_pct: number;
            assessed_on: string | null;
          }[];
        }
      >(`/projects/${projectId}/readiness`, undefined, signal),
  });

export const networkQuery = (minTransfers = 1) =>
  queryOptions({
    queryKey: ["network", minTransfers],
    queryFn: ({ signal }) =>
      get<Envelope & { lanes: LaneRow[]; sites: SiteFlowRow[] }>(
        "/network",
        { min_transfers: minTransfers },
        signal,
      ),
  });

export const similarQuery = (projectId: string, limit = 5) =>
  queryOptions({
    queryKey: ["similar", projectId, limit],
    queryFn: ({ signal }) =>
      get<
        Envelope & {
          reference_status: string;
          outcome: {
            n: number | null;
            median_variance_days: number | null;
            median_cycle_time_days: number | null;
            on_time_rate: number | null;
          };
          similar: SimilarRow[];
        }
      >(`/projects/${projectId}/similar`, { limit }, signal),
  });

// ---- Formatting ------------------------------------------------------------
// Shared so a value never renders two ways on two screens.
export function fmtDays(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${rounded}d`;
}

export function fmtNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPercent(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function fmtDate(value: string | null | undefined) {
  if (!value) return "—";
  return String(value).slice(0, 10);
}
