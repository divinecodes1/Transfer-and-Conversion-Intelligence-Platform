/**
 * Transfer & Conversion Intelligence Platform :: the shared filter scope.
 *
 * One bar, one contract, every screen — including the AI surfaces, which are
 * handed the same object. That is what makes "the briefing describes this chart"
 * a structural fact rather than a hope.
 *
 * The option lists are fetched from the governed catalogue, not hard-coded, and
 * the catalogue is entitlement-scoped: a dropdown cannot offer a portfolio the
 * reader is not allowed to see, so it never leaks the shape of the wider estate.
 */
import { useQuery } from "@tanstack/react-query";
import { FilterX } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFilters } from "@/lib/app-state";
import { filterCount, filterOptionsQuery, type Filters } from "@/lib/marts";

const ALL = "__all__";

type Dimension = {
  key: keyof Filters;
  label: string;
  option: string;
  numeric?: boolean;
};

const DIMENSIONS: Dimension[] = [
  { key: "fiscal_year", label: "Fiscal year", option: "fiscal_year", numeric: true },
  { key: "site", label: "Site", option: "target_site" },
  { key: "transfer_type", label: "Transfer type", option: "transfer_type" },
  { key: "portfolio", label: "Portfolio", option: "portfolio" },
  // What is being moved, and who buys it. Both bind on a catalogue code and
  // display the catalogue's own name — see FilterOption in lib/marts.ts.
  { key: "product_line", label: "Product line", option: "product_line" },
  { key: "application_segment", label: "Application", option: "application_segment" },
  { key: "complexity", label: "Complexity", option: "complexity_class" },
];

export function FilterBar({ compact = false }: { compact?: boolean }) {
  const { filters, setFilters, reset } = useFilters();
  const { data, isLoading } = useQuery(filterOptionsQuery());
  const options = data?.options ?? {};
  const active = filterCount(filters);

  // "Site" matches either end of a transfer, so the list is the union of the
  // two — a site lead asking about their own site means work arriving *and*
  // leaving, and offering only targets would silently hide half of it.
  //
  // Deduped by value through a Map, not a Set. Options are now {value,label}
  // objects, and a Set of objects dedupes on identity: every site that both
  // sends and receives would have appeared twice.
  const siteOptions = Array.from(
    new Map(
      [...(options["source_site"] ?? []), ...(options["target_site"] ?? [])].map(
        (option) => [option.value, option],
      ),
    ).values(),
  ).sort((a, b) => a.label.localeCompare(b.label));

  return (
    <section
      className="no-print flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-3"
      aria-label="Portfolio filters"
    >
      {DIMENSIONS.map((dimension) => {
        const list = dimension.key === "site" ? siteOptions : (options[dimension.option] ?? []);
        const current = filters[dimension.key];
        return (
          <div key={dimension.key} className={compact ? "min-w-32 flex-1 sm:max-w-36" : "min-w-36 flex-1 sm:max-w-40"}>
            <Label htmlFor={`filter-${dimension.key}`}>{dimension.label}</Label>
            <Select
              value={current === null || current === undefined ? ALL : String(current)}
              onValueChange={(value) =>
                setFilters({
                  ...filters,
                  [dimension.key]:
                    value === ALL ? null : dimension.numeric ? Number(value) : value,
                })
              }
            >
              <SelectTrigger id={`filter-${dimension.key}`} className="mt-1">
                <SelectValue placeholder={isLoading ? "Loading…" : "All"} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All</SelectItem>
                {list.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      })}

      <div className="ml-auto flex items-center gap-2 pb-0.5">
        {active > 0 ? (
          <>
            <Badge variant="secondary">
              {active} filter{active === 1 ? "" : "s"}
            </Badge>
            <Button variant="ghost" size="sm" onClick={reset}>
              <FilterX />
              Clear
            </Button>
          </>
        ) : (
          <span className="hidden text-xs text-muted-foreground lg:inline">Whole portfolio</span>
        )}
      </div>
    </section>
  );
}
