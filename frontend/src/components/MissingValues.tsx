/**
 * Fill in, where the problem is seen, the values a model reads that records
 * lack -- "1 employee record has no hours_per_week" -- instead of leaving for
 * Data › Records and coming back (simplification plan, phase 1).
 *
 * Two ways, side by side: a value for each record, or one value for every
 * record without one, kept as the attribute's default (which the server
 * writes into those records, and gives new ones too).
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getEntity, updateAttribute, updateEntity, type Id, type MissingGap } from "../api/v1";
import { formatApiError } from "../api/errors";

const INPUT = "rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900";

/** The typed text as the attribute's value, or undefined while it is not one. */
export function parseValue(text: string, dataType: string | null): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return undefined;
  if (dataType === "integer") return /^-?\d+$/.test(trimmed) ? Number(trimmed) : undefined;
  if (dataType === "number") return Number.isFinite(Number(trimmed)) ? Number(trimmed) : undefined;
  if (dataType === "boolean") return trimmed === "true" ? true : trimmed === "false" ? false : undefined;
  return trimmed;
}

function ValueInput({ label, gap, value, onChange }: { label: string; gap: MissingGap; value: string; onChange: (text: string) => void }) {
  if (gap.data_type === "enum" && gap.enum_values?.length) {
    return (
      <select aria-label={label} className={INPUT} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">choose…</option>
        {gap.enum_values.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
      </select>
    );
  }
  if (gap.data_type === "boolean") {
    return (
      <select aria-label={label} className={INPUT} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">choose…</option>
        <option value="true">yes</option>
        <option value="false">no</option>
      </select>
    );
  }
  const numeric = gap.data_type === "integer" || gap.data_type === "number";
  return (
    <input aria-label={label} className={`${INPUT} ${numeric ? "w-24 font-mono" : "w-40"}`} inputMode={numeric ? "decimal" : undefined}
      type={gap.data_type === "date" ? "date" : "text"} value={value} onChange={(event) => onChange(event.target.value)} />
  );
}

export default function MissingValues({ gap, domainId }: { gap: MissingGap; domainId: Id }) {
  const client = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({});
  const [everyone, setEveryone] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const typed = gap.records
    .map((record) => ({ record, value: parseValue(values[String(record.id)] ?? "", gap.data_type) }))
    .filter((row) => row.value !== undefined);
  const bad = gap.records.filter((record) => (values[String(record.id)] ?? "").trim() !== "" && parseValue(values[String(record.id)], gap.data_type) === undefined);
  const shared = parseValue(everyone, gap.data_type);

  async function run(work: () => Promise<void>, said: string) {
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      await work();
      setDone(said);
      setValues({});
      setEveryone("");
      // Readiness, the preflight and the records all read these values.
      await client.invalidateQueries();
    } catch (error) {
      setProblem(error instanceof Error ? formatApiError(error) : "The values could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const saveEach = () =>
    run(async () => {
      for (const { record, value } of typed) {
        // `attrs` is replaced whole: read the record, add the one value, send it back with its stamp.
        const current = await getEntity(record.id);
        await updateEntity(record.id, { attrs: { ...current.attrs, [gap.attribute]: value }, updated_at: current.updated_at });
      }
    }, `Saved ${typed.length} ${typed.length === 1 ? "value" : "values"}.`);

  const saveDefault = () =>
    run(async () => {
      if (gap.attribute_id === null) throw new Error(`${gap.attribute} is not an attribute this domain declares.`);
      await updateAttribute(gap.attribute_id, { default_value: shared });
    }, `${String(shared)} is now the default for ${gap.attribute}, filled in for every ${gap.set} without one.`);

  const name = (record: MissingGap["records"][number]) => (record.label ? `${record.label} (${record.key})` : record.key);

  return (
    <div className="mt-2 rounded-md border border-red-200 bg-white p-3 text-slate-900" data-testid="missing-values">
      <table className="text-sm">
        <caption className="mb-1 text-left text-xs text-slate-600">{gap.set} without {gap.attribute}</caption>
        <thead className="sr-only"><tr><th>Record</th><th>{gap.attribute}</th></tr></thead>
        <tbody>
          {gap.records.map((record) => (
            <tr key={String(record.id)}>
              <td className="py-1 pr-3">
                <Link className="text-blue-700 underline" to={`/domains/${domainId}/data/records/${record.id}`}>{name(record)}</Link>
              </td>
              <td className="py-1">
                <ValueInput label={`${gap.attribute} for ${record.key}`} gap={gap} value={values[String(record.id)] ?? ""}
                  onChange={(text) => setValues((current) => ({ ...current, [String(record.id)]: text }))} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {bad.length > 0 && <p role="alert" className="mt-1 text-xs text-red-700">{bad.map((r) => r.key).join(", ")}: not a {gap.data_type} value.</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          disabled={busy || typed.length === 0 || bad.length > 0} onClick={saveEach}>
          Save {typed.length > 0 ? `${typed.length} ` : ""}{typed.length === 1 ? "value" : "values"}
        </button>
        {gap.attribute_id !== null && (
          <span className="inline-flex flex-wrap items-center gap-2 text-sm text-slate-700">
            or use
            <ValueInput label={`${gap.attribute} for every ${gap.set} without one`} gap={gap} value={everyone} onChange={setEveryone} />
            for every {gap.set} without one
            <button type="button" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50"
              disabled={busy || shared === undefined} onClick={saveDefault}
              title={`Kept as ${gap.attribute}'s default, so new ${gap.set} records get it too`}>
              Use as default
            </button>
          </span>
        )}
      </div>
      {busy && <p role="status" className="mt-1 text-xs text-slate-600">Saving…</p>}
      {done && <p role="status" className="mt-1 text-xs text-emerald-700">{done}</p>}
      {problem && <p role="alert" className="mt-1 text-xs text-red-700">{problem}</p>}
    </div>
  );
}
