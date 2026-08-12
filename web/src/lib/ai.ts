/**
 * Transfer & Conversion Intelligence Platform :: typed access to the AI surface.
 *
 * Everything here degrades. `aiStatusQuery` is what the screens check before
 * rendering an AI panel at all: on a deployment with no model configured they
 * show nothing rather than an empty card with a retry button that will never
 * work.
 */
import { queryOptions } from "@tanstack/react-query";
import { get, post } from "./api";
import { activeFilters, type Filters } from "./marts";

export type AiStatus = {
  ai: {
    configured: boolean;
    provider: string;
    model: string | null;
    base_url: string | null;
    max_tokens: number;
  };
  cache: { degraded: string | null; ttl_hours: number };
};

export type Highlight = { label: string; value: string; tone: string };

export type Insight = {
  kind: string;
  headline: string | null;
  content: string;
  highlights: Highlight[];
  model: string | null;
  provider: string | null;
  data_as_of: string | null;
  generated_at: string | null;
  expires_at: string | null;
  cached: boolean;
  filters?: Record<string, unknown>;
};

export type RiskScore = {
  project_id: string;
  project_name: string | null;
  risk_score: number;
  risk_band: "low" | "medium" | "high";
  predicted_slip_days: number | null;
  drivers: string[];
  rationale: string | null;
  model: string | null;
  provider: string | null;
  data_as_of: string | null;
  generated_at: string | null;
};

export type TraceStep = {
  tool: string;
  arguments: Record<string, unknown>;
  rows: number;
  error?: string;
};

export type AskResult = {
  answer: string;
  trace: TraceStep[];
  data: { source: string; rows: Record<string, unknown>[] } | null;
  model: string | null;
  provider: string | null;
  filters: Record<string, unknown>;
  mode: string;
};

export type EmailDraft = {
  subject: string;
  body: string;
  audience: string;
  cadence: string;
  model: string | null;
  data_as_of: string | null;
};

export type AiRun = {
  run_id: number;
  job: string;
  status: string;
  trigger: string | null;
  item_count: number;
  scopes: string[] | null;
  detail: string | null;
  error_message: string | null;
  model: string | null;
  provider: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
};

export const aiStatusQuery = () =>
  queryOptions({
    queryKey: ["ai-status"],
    queryFn: ({ signal }) => get<AiStatus>("/ai/status", undefined, signal),
    staleTime: 5 * 60 * 1000,
    // A deployment without AI is a normal deployment, not a broken one.
    retry: false,
  });

export const riskQuery = () =>
  queryOptions({
    queryKey: ["ai-risk"],
    queryFn: ({ signal }) =>
      get<{ data_as_of: string | null; note: string; scores: RiskScore[] }>(
        "/ai/risk",
        undefined,
        signal,
      ),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

export const aiRunsQuery = (limit = 100) =>
  queryOptions({
    queryKey: ["ai-runs", limit],
    queryFn: ({ signal }) => get<{ runs: AiRun[] }>("/ai/runs", { limit }, signal),
    retry: false,
  });

export function fetchInsight(kind: string, filters: Filters, force = false) {
  return post<Insight>("/ai/insight", { kind, filters: activeFilters(filters), force });
}

export function askData(question: string, filters: Filters) {
  return post<AskResult>("/ai/ask", { question, filters: activeFilters(filters) });
}

export function draftEmail(filters: Filters, audience: string, cadence: string) {
  return post<EmailDraft>("/ai/email-draft", {
    filters: activeFilters(filters),
    audience,
    cadence,
  });
}

/** Risk scores keyed by project id, for joining onto the register. */
export function riskByProject(scores: RiskScore[] | undefined) {
  const map = new Map<string, RiskScore>();
  for (const score of scores ?? []) map.set(score.project_id, score);
  return map;
}
