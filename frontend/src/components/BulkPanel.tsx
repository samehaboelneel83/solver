import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";

/** What an upload answers (`app/api/bulk.py`). */
export type UploadReport = {
  ok: boolean;
  rows: number;
  written: number;
  skipped: number;
  dry_run: boolean;
  faults: { row: number; column: string | null; message: string }[];
  /** What was done unasked: links matched by a label or a code. */
  notes?: string[];
  /** Records the rows made new, and stored ones they updated (or, on a check, would). */
  created?: number | null;
  updated?: number | null;
};

/** A records file read against its kind before anything is written (`/upload/preview`). */
export type UploadPreview = {
  rows: number;
  /** Records of the kind already stored. */
  existing?: number;
  columns: { name: string; sample: string[]; unique: boolean; suggestion: string | null; matches_keys?: number }[];
  targets: { name: string; kind: string; required: boolean; links_to?: string | null }[];
};

/** What a column is read as: a target's name, a new field of its own name, or left out. */
export const NEW_FIELD = "__new__";
const LEAVE_OUT = "";

/** "Base Hospital" -> "base_hospital": the name a new field gets. */
export function fieldName(column: string): string {
  return column.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^([0-9])/, "n_$1");
}

/** The mapping the upload sends, and whether it adds fields. */
export function mappingOf(choices: Record<string, string>): { mapping: Record<string, string>; addsFields: boolean } {
  const mapping: Record<string, string> = {};
  let addsFields = false;
  for (const [column, choice] of Object.entries(choices)) {
    if (choice === NEW_FIELD) {
      mapping[column] = fieldName(column);
      addsFields = true;
    } else {
      mapping[column] = choice;
    }
  }
  return { mapping, addsFields };
}

const BUTTON = "rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60";

/**
 * Download a template and upload a filled one (queue R21), for one entity
 * type, relationship type or parameter. Every row is checked first; nothing
 * is written unless the file is clean -- or, asked, its clean rows are.
 */
export default function BulkPanel({
  base,
  what,
  exportRows = true,
}: {
  /** e.g. `/api/v1/entity-types/3`; `/template` and `/upload` follow it. */
  base: string;
  /** What the rows are, for the headings: "sites", "open_on links", "demand cells". */
  what: string;
  /** Offer "with what is stored" (a parameter's template always lists every cell). */
  exportRows?: boolean;
}) {
  const { can } = useCapabilities();
  const queryClient = useQueryClient();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [cleanOnly, setCleanOnly] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  // Records only: a column the kind has no field for becomes a new field, typed from its values.
  const recordsUpload = base.includes("/entity-types/");
  // A values file is read against the data value's index columns and `value` (benchmark, October 2026).
  const valuesUpload = base.includes("/parameters/");
  const [addFields, setAddFields] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<UploadReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const chosen = Object.values(choices);
  // Several columns read as the key make one key, joined by "_" (a route and a stop: R1_3).
  const twice = [...new Set(chosen.filter((c) => c !== LEAVE_OUT && c !== NEW_FIELD && (c !== "key" || !recordsUpload)
    && chosen.indexOf(c) !== chosen.lastIndexOf(c)))];
  const keyMissing = preview != null && recordsUpload && !chosen.includes("key");
  const keyParts = recordsUpload ? Object.keys(choices).filter((c) => choices[c] === "key") : [];
  const unread = valuesUpload && preview != null ? preview.targets.filter((t) => !chosen.includes(t.name)).map((t) => t.name) : [];

  async function readColumns() {
    const file = input.current?.files?.[0];
    setPreview(null);
    setReport(null);
    if (!file || !(recordsUpload || valuesUpload)) return;
    try {
      const body = new FormData();
      body.append("file", file);
      const found = await apiFetch<UploadPreview>(`${base}/upload/preview`, { method: "POST", body });
      if (!Array.isArray(found?.columns)) return;
      setPreview(found);
      setChoices(Object.fromEntries(found.columns.map((c) => [c.name, c.suggestion ?? (fieldName(c.name) ? NEW_FIELD : LEAVE_OUT)])));
    } catch (err) {
      setProblem(formatApiError(err));
    }
  }

  async function download(format: "csv" | "xlsx", rows: boolean) {
    setProblem(null);
    try {
      const { blob, filename } = await apiDownload(`${base}/template?format=${format}${rows ? "&rows=true" : ""}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setProblem(formatApiError(err));
    }
  }

  async function upload(withNewFields = addFields) {
    const file = input.current?.files?.[0];
    if (!file) {
      setProblem("Choose a CSV or Excel file first.");
      return;
    }
    setBusy(true);
    setProblem(null);
    setReport(null);
    try {
      const body = new FormData();
      body.append("file", file);
      let adds = withNewFields;
      if (preview) {
        const { mapping, addsFields } = mappingOf(choices);
        body.append("mapping", JSON.stringify(mapping));
        adds = adds || addsFields;
      }
      const answer = await apiFetch<UploadReport>(`${base}/upload?clean_only=${cleanOnly}&dry_run=${dryRun}${recordsUpload && adds ? "&add_fields=true" : ""}`, {
        method: "POST",
        body,
      });
      setReport(answer);
      if (answer.written > 0) await queryClient.invalidateQueries();
    } catch (err) {
      setProblem(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`${id}-heading`} className="rounded-md border border-slate-200 bg-white p-4">
      <h3 id={`${id}-heading`} className="mb-2 text-sm font-semibold text-slate-900">
        Many {what} at once
      </h3>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">Template:</span>
        <button type="button" className={BUTTON} onClick={() => download("csv", false)}>
          CSV
        </button>
        <button type="button" className={BUTTON} onClick={() => download("xlsx", false)}>
          Excel
        </button>
        {exportRows && (
          <>
            <span className="text-sm text-slate-600">With what is stored:</span>
            <button type="button" className={BUTTON} onClick={() => download("csv", true)}>
              CSV
            </button>
            <button type="button" className={BUTTON} onClick={() => download("xlsx", true)}>
              Excel
            </button>
          </>
        )}
      </div>
      {can("domain.edit") && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label htmlFor={`${id}-file`} className="sr-only">
            File to upload
          </label>
          <input id={`${id}-file`} ref={input} type="file" accept=".csv,.xlsx" className="text-sm" onChange={() => void readColumns()} />
          <label className="flex items-center gap-1 text-sm text-slate-700">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> Check only
          </label>
          <label className="flex items-center gap-1 text-sm text-slate-700">
            <input type="checkbox" checked={cleanOnly} onChange={(e) => setCleanOnly(e.target.checked)} /> Write the clean
            rows even if some are faulty
          </label>
          {recordsUpload && !preview && (
            <label className="flex items-center gap-1 text-sm text-slate-700">
              <input type="checkbox" checked={addFields} onChange={(e) => setAddFields(e.target.checked)} /> Add new
              columns as fields
            </label>
          )}
          <button
            type="button"
            onClick={() => upload()}
            disabled={busy || twice.length > 0 || keyMissing || unread.length > 0}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
          >
            {busy ? (dryRun ? "Checking…" : preview && preview.rows > 0 ? `Writing ${preview.rows.toLocaleString()} rows…` : "Writing…") : "Upload"}
          </button>
          {busy && !dryRun && (preview?.rows ?? 0) >= 1000 && (
            // A large file takes a while; without this the page looked as if nothing happened (benchmark, October 2026).
            <span role="status" className="text-sm text-slate-600">A large file can take a minute; keep this page open.</span>
          )}
        </div>
      )}
      {preview && can("domain.edit") && (
        <div className="mt-3 overflow-auto">
          <table className="text-left text-sm" aria-label="How each column is read">
            <thead>
              <tr className="text-xs text-slate-600">
                <th scope="col" className="px-2 py-1">Column in the file</th>
                <th scope="col" className="px-2 py-1">First values</th>
                <th scope="col" className="px-2 py-1">Read as</th>
              </tr>
            </thead>
            <tbody>
              {preview.columns.map((c) => (
                <tr key={c.name} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-mono">{c.name || "(no name)"}</td>
                  <td className="px-2 py-1 text-xs text-slate-600">{c.sample.join(", ")}</td>
                  <td className="px-2 py-1">
                    <select
                      aria-label={`${c.name} is read as`}
                      className="rounded border border-slate-300 px-2 py-1 text-sm"
                      value={choices[c.name] ?? LEAVE_OUT}
                      onChange={(e) => setChoices({ ...choices, [c.name]: e.target.value })}
                    >
                      {recordsUpload && <option value="key">the key{c.unique ? "" : " (values repeat!)"}</option>}
                      {recordsUpload && <option value="label">the label (the name shown)</option>}
                      {preview.targets
                        .filter((t) => !["key", "label"].includes(t.name))
                        .map((t) => (
                          <option key={t.name} value={t.name}>
                            {valuesUpload
                              ? (t.links_to ? `${t.name} — the ${t.links_to} by key` : `the ${t.name}`)
                              : t.links_to ? `${t.name} — a link to a ${t.links_to}, by key, name or code` : t.name}
                          </option>
                        ))}
                      {recordsUpload && fieldName(c.name) && !preview.targets.some((t) => t.name === fieldName(c.name)) && (
                        <option value={NEW_FIELD}>a new field “{fieldName(c.name)}”</option>
                      )}
                      <option value={LEAVE_OUT}>leave it out</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {keyMissing && <p className="mt-1 text-sm text-amber-800">Choose the column that names each record uniquely as the key.</p>}
          {keyParts.length > 1 && (
            <p className="mt-1 text-sm text-slate-700">The key is made of {keyParts.join(" and ")}, joined by “_”: {keyParts.map((k) => preview.columns.find((c) => c.name === k)?.sample[0] ?? "…").join("_")}.</p>
          )}
          {unread.length > 0 && <p className="mt-1 text-sm text-amber-800">Choose the column read as {unread.join(", ")}.</p>}
          {(() => {
            // A key that matches none of the records already stored makes every row a new record
            // (benchmark, October 2026: duplicates in three of five problems, and the check said "clean").
            const keyColumn = preview.columns.find((c) => choices[c.name] === "key");
            const stored = preview.existing ?? 0;
            if (!keyColumn || stored === 0 || (keyColumn.matches_keys ?? 0) > 0) return null;
            const better = preview.columns.find((c) => (c.matches_keys ?? 0) > 0);
            return (
              <p role="alert" className="mt-1 text-sm text-amber-800">
                {keyColumn.name} matches none of the {stored} {what} already stored: every row would be a new record.
                {better ? ` ${better.name} matches ${better.matches_keys} of them — read it as the key to update them instead.` : ""}
              </p>
            );
          })()}
          {twice.length > 0 && <p className="mt-1 text-sm text-amber-800">Two columns are read as {twice.join(", ")}; choose one.</p>}
        </div>
      )}
      {problem && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {problem}
        </p>
      )}
      {report && (
        <div role="status" className="mt-3 text-sm">
          <p className={report.ok ? "text-green-700" : "text-amber-800"}>
            {report.dry_run
              ? report.ok
                ? `All ${report.rows} rows are clean${typeof report.created === "number" ? `: they would make ${report.created} new record${report.created === 1 ? "" : "s"} and update ${report.updated ?? 0}` : ""}; nothing was written (check only).`
                : `${report.faults.length} fault(s) in ${report.rows} rows; nothing was written (check only).`
              : report.written > 0
                ? `${report.written} row(s) written` + (typeof report.created === "number" ? ` (${report.created} new, ${report.updated ?? 0} updated)` : "")
                  + (report.skipped ? `, ${report.skipped} skipped for their faults.` : ".")
                : `Nothing was written: ${report.faults.length} fault(s) to fix first.`}
          </p>
          {(report.notes ?? []).map((n) => (
            <p key={n} className="mt-1 text-slate-700">{n}.</p>
          ))}
          {recordsUpload && unknownColumns(report).length > 0 && can("domain.edit") && (
            <p className="mt-1">
              <button
                type="button"
                className={BUTTON}
                disabled={busy}
                onClick={() => {
                  setAddFields(true);
                  void upload(true);
                }}
              >
                Add {unknownColumns(report).join(", ")} as new field{unknownColumns(report).length > 1 ? "s" : ""} and upload again
              </button>
            </p>
          )}
          {report.faults.length > 0 && (
            <div className="mt-2 max-h-64 overflow-auto">
              <table className="text-left text-xs">
                <thead>
                  <tr className="text-slate-600">
                    <th scope="col" className="px-2 py-1">Row</th>
                    <th scope="col" className="px-2 py-1">Column</th>
                    <th scope="col" className="px-2 py-1">Fault</th>
                  </tr>
                </thead>
                <tbody>
                  {report.faults.map((f, k) => (
                    <tr key={k} className="border-t border-slate-100">
                      <td className="px-2 py-1 font-mono">{f.row}</td>
                      <td className="px-2 py-1 font-mono">{f.column ?? "—"}</td>
                      <td className="px-2 py-1">{f.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** Columns a records file carries that the kind has no field for (row 1 faults). */
function unknownColumns(report: UploadReport): string[] {
  return report.faults
    .filter((f) => f.row === 1 && f.column && f.message.startsWith("is not a column"))
    .map((f) => f.column as string)
    .filter((c) => /^[a-z][a-z0-9_]*$/.test(c));
}
