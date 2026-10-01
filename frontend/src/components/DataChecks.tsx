import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import type { Id } from "../api/v1";

export type DataFinding = {
  code: "loop" | "too_deep" | "outside_tree" | "inactive_target" | "empty_reference";
  severity: "error" | "warning" | "info";
  says: string;
  count: number;
  records: { id: Id; key: string; label: string | null }[];
  relationship?: string;
  attribute?: string | null;
  kind?: string;
};

const TONE: Record<DataFinding["severity"], { box: string; word: string }> = {
  error: { box: "border-red-300 bg-red-50", word: "Must fix" },
  warning: { box: "border-amber-300 bg-amber-50", word: "Check" },
  info: { box: "border-slate-200 bg-white", word: "Note" },
};

const TITLE: Record<DataFinding["code"], string> = {
  loop: "Chain loops back on itself",
  too_deep: "Deeper than the limit",
  outside_tree: "Not placed in the tree",
  inactive_target: "Refers to a switched-off record",
  empty_reference: "Reference left empty",
};

function Finding({ finding }: { finding: DataFinding }) {
  const [all, setAll] = useState(false);
  const shown = all ? finding.records : finding.records.slice(0, 12);
  const tone = TONE[finding.severity];
  return (
    <li className={`rounded-md border p-3 ${tone.box}`} data-testid={`finding-${finding.code}`}>
      <p className="text-sm">
        <span className="mr-2 rounded bg-white/70 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide">{tone.word}</span>
        <strong>{TITLE[finding.code]}</strong>
        <span className="ml-2 text-slate-600">{finding.count} record{finding.count === 1 ? "" : "s"}</span>
      </p>
      <p className="mt-1 text-sm text-slate-700">{finding.says}</p>
      <ul className="mt-2 flex flex-wrap gap-1.5 text-sm">
        {shown.map((r) => (
          <li key={r.id}>
            <Link to={`/entities/${r.id}`} className="rounded bg-white px-1.5 py-0.5 text-blue-700 underline">
              {r.label ? `${r.label} (${r.key})` : r.key}
            </Link>
          </li>
        ))}
        {finding.records.length > shown.length && (
          <li>
            <button type="button" className="px-1.5 py-0.5 text-blue-700 underline" onClick={() => setAll(true)}>
              {finding.records.length - shown.length} more
            </button>
          </li>
        )}
        {finding.count > finding.records.length && (
          <li className="px-1.5 py-0.5 text-slate-500">and {finding.count - finding.records.length} not listed</li>
        )}
      </ul>
    </li>
  );
}

/**
 * The domain's data checked as a whole (`app/api/data_checks.py`): loops in recursive
 * relationships, chains deeper than a limit the reader sets, records left outside a tree, and
 * reference fields that point at switched-off records or are empty.
 */
export default function DataChecks({ domainId }: { domainId: Id }) {
  const [maxDepth, setMaxDepth] = useState(10);
  const checks = useQuery({
    queryKey: ["v1", "data-checks", domainId, maxDepth],
    queryFn: () =>
      apiFetch<{ findings: DataFinding[] }>(`/api/v1/domains/${domainId}/data-checks?max_depth=${maxDepth}`),
  });
  const findings = checks.data?.findings ?? [];
  return (
    <section aria-labelledby="data-checks" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="data-checks" className="text-lg font-semibold text-slate-900">
            Recursive relationships and references
          </h2>
          <p className="text-sm text-slate-600">Checked across all records of this domain, each time this page opens.</p>
        </div>
        <label className="text-sm text-slate-700">
          Deepest level allowed{" "}
          <input
            type="number"
            min={1}
            max={1000}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Math.max(1, Number(e.target.value) || 1))}
            className="ml-1 w-20 rounded-md border border-slate-300 px-2 py-1"
          />
        </label>
      </div>
      {checks.isLoading && <p className="text-sm text-slate-500">Checking…</p>}
      {checks.isError && <p className="text-sm text-red-700">Could not check: {formatApiError(checks.error)}</p>}
      {checks.isSuccess && findings.length === 0 && (
        <p className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900" data-testid="checks-clean">
          No loops, nothing too deep, nothing left outside a tree, and every reference names an active record.
        </p>
      )}
      {findings.length > 0 && (
        <ul className="space-y-2">
          {findings.map((f, i) => (
            <Finding key={`${f.code}-${f.relationship ?? ""}-${f.attribute ?? ""}-${i}`} finding={f} />
          ))}
        </ul>
      )}
    </section>
  );
}
