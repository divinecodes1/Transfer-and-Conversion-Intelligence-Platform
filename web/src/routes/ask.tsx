/**
 * Transfer & Conversion Intelligence Platform :: ask the platform.
 *
 * Two assistants on one screen, deliberately.
 *
 *   **Governed** is the deterministic resolver: it maps a question onto a
 *   registered metric using the catalogue's own vocabulary, and abstains when
 *   the question could mean several. It cannot hallucinate, and its answer
 *   carries a full provenance envelope.
 *
 *   **Model** is the tool-calling path: wider vocabulary, and it shows every
 *   tool call it made instead of a provenance envelope.
 *
 * Showing them side by side is the point. The interesting cases are the ones
 * where the governed assistant refuses and the model answers — that is exactly
 * where a reader should look hardest, and hiding the difference behind one
 * "Ask" button is how a platform loses track of which of its answers are
 * guaranteed.
 */
import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { BarChart3, BookOpenCheck, CircleHelp, Filter, Send, ShieldCheck, Sparkles } from "lucide-react";
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
import { AskPanel, Prose, useAiEnabled } from "@/components/ai";
import { PageHeader } from "@/components/panels";
import { askAssistant } from "@/lib/api";
import { useFilters } from "@/lib/app-state";
import { activeFilters, fmtNumber } from "@/lib/marts";

type GovernedAnswer = {
  answer?: string;
  intent?: string;
  mode?: string;
  reason?: string;
  candidates?: string[];
  metric?: { metric_code: string; business_name: string; definition: string; version: string };
  filters?: Record<string, unknown>;
  rows?: Record<string, unknown>[];
  provenance_complete?: boolean;
  data_as_of?: string;
  sources?: { title?: string; text?: string }[];
  escalated_from?: string | null;
  trace?: { tool: string; rows: number }[];
};

function GovernedPanel() {
  const [question, setQuestion] = React.useState("");
  const mutation = useMutation({
    mutationFn: (value: string) =>
      askAssistant<GovernedAnswer>({ question: value, mode: "deterministic" }),
  });

  const result = mutation.data;
  const rows = result?.rows ?? [];
  const columns = rows.length > 0 ? Object.keys(rows[0]!) : [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 text-primary" />
            Ask your data
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Ask about delivery, cycle time, schedule drift, forecast accuracy or a project.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
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
              placeholder="e.g. Which site drives most of our replans?"
              aria-label="Your question"
              className="h-11"
            />
            <Button
              type="submit"
              className="h-11"
              disabled={mutation.isPending || question.trim().length < 3}
            >
              <Send />
              Ask
            </Button>
          </form>

          <div className="grid gap-2 sm:grid-cols-2">
            {[
              "Which transfer type has the highest cycle time?",
              "What does schedule drift mean?",
              "Which projects are late?",
              "Show me forecast error by horizon",
            ].map((text) => (
              <button
                key={text}
                type="button"
                onClick={() => {
                  setQuestion(text);
                  mutation.mutate(text);
                }}
                className="rounded-md border border-border px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                {text}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {mutation.isPending ? <Skeleton className="h-20 w-full" /> : null}
      {mutation.isError ? (
        <Card className="border-bad/25 bg-bad/5">
          <CardContent className="p-4 text-sm text-bad">
            {(mutation.error as Error).message}
          </CardContent>
        </Card>
      ) : null}

      {result ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-ok" />
              Governed answer
            </CardTitle>
            <div className="flex items-center gap-1.5">
              <Badge variant="outline">{result.intent ?? "—"}</Badge>
              {result.provenance_complete ? (
                <Badge variant="ok" dot>
                  provenance complete
                </Badge>
              ) : (
                <Badge variant="warn" dot>
                  no envelope
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <Prose>{result.answer ?? result.reason ?? "No answer."}</Prose>

            {/* An abstention is a result, not a failure — the candidates are the
                useful part, because choosing one silently is how two people end
                up quoting different numbers for "late". */}
            {result.candidates?.length ? (
              <div className="rounded-md border border-warn/25 bg-warn/5 p-3">
                <div className="flex items-center gap-1.5 text-xs font-medium text-warn">
                  <CircleHelp className="size-3.5" />
                  This maps to more than one governed metric
                </div>
                <ul className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
                  {result.candidates.map((candidate) => (
                    <li key={candidate} className="num">
                      {candidate}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {result.metric ? (
              <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
                <div className="num font-medium">
                  {result.metric.metric_code} v{result.metric.version}
                </div>
                <div className="mt-0.5 text-muted-foreground">{result.metric.definition}</div>
              </div>
            ) : null}

            {rows.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    {columns.map((column) => (
                      <TableHead key={column}>{column.replace(/_/g, " ")}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.slice(0, 20).map((row, index) => (
                    <TableRow key={index}>
                      {columns.map((column) => (
                        <TableCell key={column} className="num">
                          {row[column] === null || row[column] === undefined
                            ? "—"
                            : typeof row[column] === "number"
                              ? fmtNumber(row[column] as number, 1)
                              : String(row[column])}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}

            {result.sources?.length ? (
              <div className="border-t border-border pt-2 text-xs text-muted-foreground">
                Supporting documents (explanatory only — they never supply a number):{" "}
                {result.sources.map((source) => source.title).filter(Boolean).join(", ")}
              </div>
            ) : null}

            <div className="border-t border-border pt-2 text-xs text-muted-foreground">
              Answered deterministically from the metric catalogue. No model was involved.
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export function AskScreen() {
  const { enabled } = useAiEnabled();
  const { filters } = useFilters();
  const [tab, setTab] = React.useState<"governed" | "model">("governed");
  const scope = Object.entries(activeFilters(filters));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Ask AI"
        description="Ask the governed metric layer a plain-language question. Your portfolio filters are applied automatically."
      />

      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => setTab("governed")}
          className={
            tab === "governed"
              ? "inline-flex items-center gap-1.5 rounded-md border border-primary bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
              : "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
          }
        >
          <ShieldCheck className="size-4" />
          Governed
        </button>
        <button
          type="button"
          onClick={() => setTab("model")}
          disabled={!enabled}
          className={
            tab === "model"
              ? "inline-flex items-center gap-1.5 rounded-md border border-primary bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
              : "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent disabled:opacity-50"
          }
          title={enabled ? undefined : "No model is configured for this deployment"}
        >
          <Sparkles className="size-4" />
          Model
        </button>
      </div>

      <Card className="border-dashed">
        <CardContent className="p-3 text-xs text-muted-foreground">
          {tab === "governed" ? (
            <>
              <span className="font-medium text-foreground">Governed:</span> resolves your question
              against the metric catalogue and answers with a full provenance envelope. It refuses
              rather than guessing — including when a question maps to several registered metrics.
            </>
          ) : (
            <>
              <span className="font-medium text-foreground">Model:</span> a model chooses which
              governed tool to call and reads the result. Wider vocabulary, no provenance envelope
              — every tool call it made is shown instead, so you can check the working.
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div>{tab === "governed" ? <GovernedPanel /> : <AskPanel filters={filters} />}</div>

        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-ok" />
                {tab === "governed" ? "Why this answer is trusted" : "How the model is checked"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs text-muted-foreground">
              <div className="flex gap-2">
                <BookOpenCheck className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>Definitions and populations come from the registered metric catalogue.</span>
              </div>
              <div className="flex gap-2">
                <BarChart3 className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>Figures are queried from governed marts, never invented from prose.</span>
              </div>
              <div className="flex gap-2">
                <CircleHelp className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>Ambiguous questions are clarified or refused instead of silently guessed.</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Filter className="size-4 text-primary" />
                Current scope
              </CardTitle>
            </CardHeader>
            <CardContent>
              {scope.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {scope.map(([key, value]) => (
                    <Badge key={key} variant="secondary">
                      {key.replace(/_/g, " ")}: {value}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Whole portfolio · all available projects</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
