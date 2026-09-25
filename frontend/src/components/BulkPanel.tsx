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
};

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
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<UploadReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

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

  async function upload() {
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
      const answer = await apiFetch<UploadReport>(`${base}/upload?clean_only=${cleanOnly}&dry_run=${dryRun}`, {
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
          <input id={`${id}-file`} ref={input} type="file" accept=".csv,.xlsx" className="text-sm" />
          <label className="flex items-center gap-1 text-sm text-slate-700">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> Check only
          </label>
          <label className="flex items-center gap-1 text-sm text-slate-700">
            <input type="checkbox" checked={cleanOnly} onChange={(e) => setCleanOnly(e.target.checked)} /> Write the clean
            rows even if some are faulty
          </label>
          <button
            type="button"
            onClick={upload}
            disabled={busy}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
          >
            {busy ? "Checking…" : "Upload"}
          </button>
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
                ? `All ${report.rows} rows are clean; nothing was written (check only).`
                : `${report.faults.length} fault(s) in ${report.rows} rows; nothing was written (check only).`
              : report.written > 0
                ? `${report.written} row(s) written` + (report.skipped ? `, ${report.skipped} skipped for their faults.` : ".")
                : `Nothing was written: ${report.faults.length} fault(s) to fix first.`}
          </p>
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
