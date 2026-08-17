/**
 * Transfer & Conversion Intelligence Platform :: the AI surfaces.
 *
 * Every one of them follows the same three rules, which is what makes generated
 * text safe to put next to a governed number:
 *
 *   1. **They disappear when there is no model.** `aiStatusQuery` gates each
 *      panel. A deployment that was never given a key shows dashboards and the
 *      deterministic assistant, not a row of retry buttons.
 *
 *   2. **They are labelled.** Every panel names the model that wrote it and the
 *      warehouse vintage it read. A reader can always tell a narrative from a
 *      metric.
 *
 *   3. **The numbers beside them come from the metric layer, not from the
 *      prose.** The highlight chips are computed from the same snapshot the
 *      model was given — never parsed out of what it wrote — so a card cannot
 *      contradict the chart above it even if the model miscounts in a sentence.
 */
import * as React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import {
  Bot,
  Copy,
  RefreshCw,
  Send,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  aiStatusQuery,
  askData,
  draftEmail,
  fetchInsight,
  riskQuery,
  type AskResult,
  type Highlight,
  type Insight,
  type RiskScore,
} from "@/lib/ai";
import { useFilters } from "@/lib/app-state";
import { type Filters } from "@/lib/marts";
import { cn } from "@/lib/utils";

/** Whether this deployment has a model at all. */
export function useAiEnabled() {
  const { data } = useQuery(aiStatusQuery());
  return { enabled: Boolean(data?.ai?.configured), status: data };
}

const TONE_CLASS: Record<string, string> = {
  ok: "border-ok/25 bg-ok/10 text-ok",
  warn: "border-warn/25 bg-warn/10 text-warn",
  bad: "border-bad/25 bg-bad/10 text-bad",
  muted: "border-border bg-muted text-muted-foreground",
};

function Highlights({ items }: { items: Highlight[] }) {
  if (!items?.length) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item.label}
          className={cn(
            "inline-flex items-baseline gap-1.5 rounded-md border px-2 py-1 text-xs",
            TONE_CLASS[item.tone] ?? TONE_CLASS["muted"],
          )}
        >
          <span className="opacity-80">{item.label}</span>
          <span className="num font-semibold">{item.value}</span>
        </span>
      ))}
    </div>
  );
}

/** Markdown, restricted to what a briefing legitimately needs. */
export function Prose({ children }: { children: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_h3]:mt-3 [&_h3]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_strong]:font-semibold [&_table]:w-full [&_td]:py-1 [&_th]:py-1 [&_th]:text-left">
      <Markdown>{children}</Markdown>
    </div>
  );
}

function ModelFootnote({
  model,
  provider,
  dataAsOf,
  cached,
  generatedAt,
}: {
  model?: string | null;
  provider?: string | null;
  dataAsOf?: string | null;
  cached?: boolean;
  generatedAt?: string | null;
}) {
  return (
    <div className="mt-3 border-t border-border pt-2 text-xs text-muted-foreground">
      Written by <span className="num">{model ?? "a model"}</span>
      {provider ? ` (${provider})` : null} from governed metrics as of{" "}
      <span className="num">{dataAsOf ? String(dataAsOf).slice(0, 10) : "—"}</span>
      {cached ? " · cached" : " · generated just now"}
      {generatedAt ? ` · ${new Date(generatedAt).toLocaleString()}` : null}. Narrative, not a
      governed metric — the figures above it come from the metric layer.
    </div>
  );
}

// ---- Insight card ----------------------------------------------------------
export function AiInsightCard({
  kind = "portfolio_overview",
  title = "AI briefing",
  description,
  filters,
}: {
  kind?: string;
  title?: string;
  description?: string;
  filters: Filters;
}) {
  const { enabled } = useAiEnabled();
  const [insight, setInsight] = React.useState<Insight | null>(null);

  const mutation = useMutation({
    mutationFn: (force: boolean) => fetchInsight(kind, filters, force),
    onSuccess: setInsight,
  });

  // Refetch whenever the scope changes: a briefing about a different filter set
  // is not a stale briefing, it is a wrong one.
  const scopeKey = JSON.stringify(filters);
  React.useEffect(() => {
    if (!enabled) return;
    setInsight(null);
    mutation.mutate(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, scopeKey, kind]);

  if (!enabled) return null;

  return (
    // The AI surface is tinted, not decorated. A pale teal ground and a teal
    // border mark it as generated content while keeping it inside the same
    // visual system as every other panel — no purple, no gradient, no glow.
    // The point is that a reader can tell where a narrative came from, not
    // that the panel looks exciting.
    <Card className="border-primary-200 bg-primary-050">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" />
            {title}
          </CardTitle>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => mutation.mutate(true)}
          disabled={mutation.isPending}
          title="Regenerate against the current warehouse vintage"
        >
          <RefreshCw className={mutation.isPending ? "animate-spin" : undefined} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent>
        {mutation.isPending && !insight ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        ) : mutation.isError ? (
          <div className="flex items-start gap-2 rounded-md border border-warn/25 bg-warn/5 p-3 text-xs">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" />
            <div>
              <div className="font-medium text-warn">The briefing could not be written</div>
              <p className="mt-0.5 text-muted-foreground">
                {(mutation.error as Error).message}
              </p>
              <p className="mt-1 text-muted-foreground">
                The numbers on this page are unaffected — they come from the metric layer.
              </p>
            </div>
          </div>
        ) : insight ? (
          <>
            <Highlights items={insight.highlights ?? []} />
            <Prose>{insight.content}</Prose>
            <ModelFootnote
              model={insight.model}
              provider={insight.provider}
              dataAsOf={insight.data_as_of}
              cached={insight.cached}
              generatedAt={insight.generated_at}
            />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---- Risk badge ------------------------------------------------------------
const BAND_VARIANT = { low: "ok", medium: "warn", high: "bad" } as const;

/**
 * A model's estimate, and labelled as one.
 *
 * Never rendered as a governed metric: the tooltip carries the drivers and the
 * rationale so a reader can check the claim against the register row it sits on.
 */
export function RiskBadge({ score }: { score: RiskScore | undefined }) {
  if (!score) return <span className="text-xs text-muted-foreground">—</span>;
  const detail = [
    score.rationale,
    score.drivers?.length ? `Drivers: ${score.drivers.join(", ")}` : null,
    score.predicted_slip_days !== null
      ? `Predicted slip: ${score.predicted_slip_days}d`
      : null,
    score.model ? `Estimated by ${score.model}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <Badge dot variant={BAND_VARIANT[score.risk_band] ?? "muted"} title={detail}>
      {score.risk_band} <span className="num">{score.risk_score}</span>
    </Badge>
  );
}

export function useRiskScores() {
  const { enabled } = useAiEnabled();
  const query = useQuery({ ...riskQuery(), enabled });
  const map = React.useMemo(() => {
    const out = new Map<string, RiskScore>();
    for (const score of query.data?.scores ?? []) out.set(score.project_id, score);
    return out;
  }, [query.data]);
  return { ...query, byProject: map, enabled };
}

// ---- Ask, and the trace it came with --------------------------------------
export function AskPanel({ filters }: { filters: Filters }) {
  const [question, setQuestion] = React.useState("");
  const [result, setResult] = React.useState<AskResult | null>(null);
  const mutation = useMutation({
    mutationFn: (value: string) => askData(value, filters),
    onSuccess: setResult,
  });

  const suggestions = [
    "Which transfer type has the highest median cycle time?",
    "How has on-time delivery moved over the last three fiscal years?",
    "Which projects are more than 60 days behind their baseline?",
    "How accurate are our forecasts 90 days out?",
  ];

  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (question.trim().length >= 3) mutation.mutate(question.trim());
        }}
        className="flex gap-2"
      >
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about cycle time, drift, forecast accuracy or a project…"
          aria-label="Your question"
        />
        <Button type="submit" disabled={mutation.isPending || question.trim().length < 3}>
          <Send />
          Ask
        </Button>
      </form>

      <div className="flex flex-wrap gap-1.5">
        {suggestions.map((text) => (
          <button
            key={text}
            type="button"
            onClick={() => {
              setQuestion(text);
              mutation.mutate(text);
            }}
            className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            {text}
          </button>
        ))}
      </div>

      {mutation.isPending ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-full" />
          </CardContent>
        </Card>
      ) : null}

      {mutation.isError ? (
        <Card className="border-bad/25 bg-bad/5">
          <CardContent className="p-4 text-sm text-bad">
            {(mutation.error as Error).message}
          </CardContent>
        </Card>
      ) : null}

      {result ? <AnswerCard result={result} /> : null}
    </div>
  );
}

function AnswerCard({ result }: { result: AskResult }) {
  const rows = result.data?.rows ?? [];
  const columns = rows.length > 0 ? Object.keys(rows[0]!) : [];

  return (
    <div className="space-y-3">
      <Card>
        <CardContent className="p-4">
          <Prose>{result.answer}</Prose>
          <ModelFootnote model={result.model} provider={result.provider} />
        </CardContent>
      </Card>

      {/* The working, shown by default rather than hidden behind a disclosure.
          An answer nobody can trace back is not usable for a decision. */}
      <Card>
        <CardHeader>
          <CardTitle className="text-label uppercase text-muted-foreground">
            How this was answered
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {result.trace.length === 0 ? (
            <p className="text-xs text-muted-foreground">No governed tool was called.</p>
          ) : (
            result.trace.map((step, index) => (
              <div key={index} className="flex flex-wrap items-baseline gap-2 text-xs">
                <Badge variant="outline" className="num">
                  {step.tool}
                </Badge>
                <span className="num text-muted-foreground">
                  {JSON.stringify(step.arguments)}
                </span>
                <span className={step.error ? "text-bad" : "text-muted-foreground"}>
                  {step.error ? step.error : `${step.rows} row${step.rows === 1 ? "" : "s"}`}
                </span>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {rows.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-label uppercase text-muted-foreground">
              The data behind the answer
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  {columns.map((column) => (
                    <TableHead key={column}>{column.replace(/_/g, " ")}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.slice(0, 25).map((row, index) => (
                  <TableRow key={index}>
                    {columns.map((column) => (
                      <TableCell key={column} className="num">
                        {row[column] === null || row[column] === undefined
                          ? "—"
                          : String(row[column])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

// ---- Report email draft ----------------------------------------------------
const AUDIENCES = [
  { value: "steering_committee", label: "Steering committee" },
  { value: "site_leads", label: "Site leads" },
  { value: "project_managers", label: "Project managers" },
];

export function ReportEmailDraft({ filters }: { filters: Filters }) {
  const { enabled } = useAiEnabled();
  const [audience, setAudience] = React.useState("steering_committee");
  const [copied, setCopied] = React.useState(false);
  const mutation = useMutation({
    mutationFn: () => draftEmail(filters, audience, "weekly"),
  });

  if (!enabled) return null;
  const draft = mutation.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          Draft the report email
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Audience-aware, from the current filter scope. A draft to copy — nothing is sent.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {AUDIENCES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setAudience(option.value)}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs",
                audience === option.value
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {option.label}
            </button>
          ))}
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            <RefreshCw className={mutation.isPending ? "animate-spin" : undefined} />
            {draft ? "Redraft" : "Draft"}
          </Button>
        </div>

        {mutation.isError ? (
          <p className="text-xs text-bad">{(mutation.error as Error).message}</p>
        ) : null}

        {draft ? (
          <div className="rounded-md border border-border bg-muted/40 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="text-sm font-medium">{draft.subject}</div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  void navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
              >
                <Copy />
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <div className="mt-2">
              <Prose>{draft.body}</Prose>
            </div>
            <ModelFootnote model={draft.model} dataAsOf={draft.data_as_of} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---- Docked assistant ------------------------------------------------------
type Turn = { role: "user" | "assistant"; text: string; trace?: AskResult["trace"] };

/**
 * The assistant, available on every screen.
 *
 * It inherits the page's filter scope, so "what about last year?" means the same
 * thing here as it does in the charts behind it.
 */
export function AiAssistant() {
  const { enabled } = useAiEnabled();
  const { filters } = useFilters();
  const [open, setOpen] = React.useState(false);
  const [input, setInput] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const endRef = React.useRef<HTMLDivElement>(null);

  const mutation = useMutation({
    mutationFn: (value: string) => askData(value, filters),
    onSuccess: (result) =>
      setTurns((previous) => [
        ...previous,
        { role: "assistant", text: result.answer, trace: result.trace },
      ]),
    onError: (error: Error) =>
      setTurns((previous) => [
        ...previous,
        { role: "assistant", text: `I could not answer that: ${error.message}` },
      ]),
  });

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, mutation.isPending]);

  if (!enabled) return null;

  const send = () => {
    const value = input.trim();
    if (value.length < 3) return;
    setTurns((previous) => [...previous, { role: "user", text: value }]);
    setInput("");
    mutation.mutate(value);
  };

  if (!open) {
    return (
      <Button
        className="no-print fixed bottom-4 right-4 z-50 shadow-lg"
        onClick={() => setOpen(true)}
      >
        <Bot />
        Ask AI Copilot
      </Button>
    );
  }

  return (
    <div className="no-print fixed bottom-4 right-4 z-50 flex h-[32rem] w-[26rem] max-w-[calc(100vw-2rem)] flex-col rounded-lg border border-border bg-card shadow-xl">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bot className="size-4 text-primary" />
          AI Copilot
        </div>
        <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close">
          <X />
        </Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {turns.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Ask about any governed metric. Answers use the filters set on this page, and every
            tool call is shown.
          </p>
        ) : null}
        {turns.map((turn, index) => (
          <div
            key={index}
            className={cn(
              "rounded-md px-3 py-2 text-sm",
              turn.role === "user"
                ? "ml-6 bg-primary/10 text-foreground"
                : "mr-2 bg-muted",
            )}
          >
            {turn.role === "assistant" ? <Prose>{turn.text}</Prose> : turn.text}
            {turn.trace?.length ? (
              <div className="mt-2 flex flex-wrap gap-1 border-t border-border pt-1.5">
                {turn.trace.map((step, stepIndex) => (
                  <span key={stepIndex} className="num text-xs text-muted-foreground">
                    {step.tool}({step.rows})
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {mutation.isPending ? (
          <div className="mr-2 space-y-1.5 rounded-md bg-muted px-3 py-2">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      <div className="flex gap-2 border-t border-border p-2">
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          placeholder="Ask a question…"
          aria-label="Message the assistant"
        />
        <Button size="icon" onClick={send} disabled={mutation.isPending} aria-label="Send">
          <Send />
        </Button>
      </div>
    </div>
  );
}
