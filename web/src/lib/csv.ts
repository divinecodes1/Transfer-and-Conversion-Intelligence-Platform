/**
 * Transfer & Conversion Intelligence Platform :: CSV export.
 *
 * Export only. The console never *ingests* a file: the API is opened read-only,
 * so a write is refused by the database rather than by convention, and an upload
 * form here would need that property relaxed to work. Ingestion runs through the
 * layered pipeline (`etl/ingest.py`), where the quality tiers and the quarantine
 * live — see the Ingestion screen.
 *
 * The exported rows are exactly the rows the panel rendered, so a spreadsheet a
 * reader builds from this and the dashboard they built it from cannot disagree.
 */

function escape(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  // Quote whenever the value could otherwise break the row, and double any
  // embedded quote. A project named `FAB_TO_FAB, DRE->KLM` is normal data.
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  if (rows.length === 0) return "";
  const keys = columns ?? Object.keys(rows[0]!);
  const header = keys.map(escape).join(",");
  const body = rows.map((row) => keys.map((key) => escape(row[key])).join(","));
  return [header, ...body].join("\r\n");
}

export function downloadCsv(
  filename: string,
  rows: Record<string, unknown>[],
  columns?: string[],
) {
  const csv = toCsv(rows, columns);
  if (!csv) return;
  // A BOM, so Excel opens UTF-8 correctly instead of mangling site names.
  const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
