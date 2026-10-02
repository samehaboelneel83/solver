import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";
import type { Id } from "../api/v1";

/** What a workbook upload answers (`app/api/workbook.py`). */
export type WorkbookReport = {
  ok: boolean;
  dry_run: boolean;
  kept: boolean;
  order: string[];
  sheets: {
    sheet: string;
    kind: string;
    /** Records of a kind, a relationship's links, or a parameter's values. */
    what?: "records" | "links" | "values";
    rows: number;
    written: number;
    second_pass: string[];
    faults: { row: number; column: string | null; message: string }[];
  }[];
  ignored: string[];
};

const BUTTON = "rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60";

/**
 * Every kind of record in one Excel file, one sheet each. Check first: the file is read in the
 * order the kinds depend on one another, references inside a sheet (a parent, a manager) are
 * resolved after every record exists, and every fault is listed by sheet, row and column. Only
 * a clean check can be imported, and the import keeps all of it or none.
 */
export default function WorkbookPanel({ domainId }: { domainId: Id }) {
  const { can } = useCapabilities();
  const queryClient = useQueryClient();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<WorkbookReport | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const base = `/api/v1/domains/${domainId}/workbook`;

  async function download(rows: boolean) {
    setProblem(null);
    try {
      const { blob, filename } = await apiDownload(`${base}${rows ? "?rows=true" : ""}`);
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

  async function send(dryRun: boolean) {
    const file = input.current?.files?.[0];
    if (!file) {
      setProblem("Choose an Excel workbook first.");
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const answer = await apiFetch<WorkbookReport>(`${base}?dry_run=${dryRun}`, { method: "POST", body });
      setReport(answer);
      if (answer.kept) await queryClient.invalidateQueries();
    } catch (err) {
      setProblem(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const faults = report?.sheets.reduce((n, s) => n + s.faults.length, 0) ?? 0;
  return (
    <section aria-labelledby={`${id}-heading`} className="rounded-xl border border-slate-200 bg-white p-5" data-testid="workbook-panel">
      <h2 id={`${id}-heading`} className="font-semibold text-slate-900">
        All records in one workbook
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        One sheet per kind of record, plus “links …” sheets for relationships and “values …” sheets for parameters.
        Kinds are read in the order they depend on each other, references within a sheet (a parent, a manager) are
        filled in once every record exists, and links and values come last.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">Download:</span>
        <button type="button" className={BUTTON} onClick={() => download(false)}>
          Empty template
        </button>
        <button type="button" className={BUTTON} onClick={() => download(true)}>
          With what is stored
        </button>
      </div>
      {can("domain.edit") && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label htmlFor={`${id}-file`} className="sr-only">
            Workbook to upload
          </label>
          <input
            id={`${id}-file`}
            ref={input}
            type="file"
            accept=".xlsx"
            className="text-sm"
            onChange={(e) => {
              setReport(null);
              setFileName(e.target.files?.[0]?.name ?? null);
            }}
          />
          <button type="button" className={BUTTON} disabled={busy || !fileName} onClick={() => send(true)}>
            {busy ? "Working…" : "Check"}
          </button>
          <button
            type="button"
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            disabled={busy || !report?.dry_run || !report.ok}
            title={!report?.dry_run || !report.ok ? "Check the workbook first; only a clean one can be imported" : undefined}
            onClick={() => send(false)}
          >
            Import
          </button>
        </div>
      )}
      {problem && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {problem}
        </p>
      )}
      {report && (
        <div className="mt-4 space-y-3" data-testid="workbook-report">
          <p
            role="status"
            className={`rounded-md px-3 py-2 text-sm ${report.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-900"}`}
          >
            {report.kept
              ? `Imported: ${report.sheets.reduce((n, s) => n + s.written, 0)} records across ${report.sheets.length} sheets.`
              : report.ok
                ? "Clean — nothing was written yet. Import to keep it."
                : `${faults} problem${faults === 1 ? "" : "s"} — nothing was written. Fix them in the workbook and check again.`}
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-1">Order</th>
                <th>Sheet</th>
                <th>Rows</th>
                <th>Problems</th>
                <th>Filled in after</th>
              </tr>
            </thead>
            <tbody>
              {report.sheets.map((s, i) => (
                <tr key={s.sheet} className="border-t border-slate-100 align-top">
                  <td className="py-1">{i + 1}</td>
                  <td className="font-mono">{s.sheet}</td>
                  <td>{s.rows}</td>
                  <td>
                    {s.faults.length === 0 ? (
                      <span className="text-emerald-700">none</span>
                    ) : (
                      <ul className="space-y-0.5 text-red-800">
                        {s.faults.slice(0, 20).map((f, j) => (
                          <li key={j}>
                            row {f.row}
                            {f.column ? `, ${f.column}` : ""}: {f.message}
                          </li>
                        ))}
                        {s.faults.length > 20 && <li>and {s.faults.length - 20} more</li>}
                      </ul>
                    )}
                  </td>
                  <td className="font-mono text-xs text-slate-600">{s.second_pass.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {report.ignored.length > 0 && (
            <p className="text-xs text-slate-500">
              Not a kind of record, relationship or parameter here, so not read: {report.ignored.join(", ")}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
