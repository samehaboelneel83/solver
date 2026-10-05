import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ChevronDown, ChevronRight, Loader2, Wand2, X } from "lucide-react";
import {
  applyDomainRecords, proposeDomainRecords,
  type AutoApplied, type AutoChoice, type AutoMapping,
} from "../../api/gis";
import { formatApiError } from "../../api/errors";

/**
 * All of a domain's map data onto its kinds of record, in one go (backend `app/gis/auto_records.py`).
 *
 * Every layer of every map data is matched to the kind it belongs to -- by record keys in common, by
 * name, by fields -- and shown here before anything is written: the kind, the key, how many records it
 * updates and adds, the fields, anything that would not fit. Change a layer's kind or key and it is
 * mapped again; apply writes every layer at once, all or nothing.
 */
const NEW = "__new__";
const SKIP = "__skip__";

function confidence(m: AutoMapping): { label: string; tone: string } {
  if (m.action === "new") return { label: "new kind", tone: "bg-sky-100 text-sky-800" };
  if (m.confidence >= 0.8) return { label: "sure", tone: "bg-emerald-100 text-emerald-800" };
  if (m.confidence >= 0.5) return { label: "likely", tone: "bg-amber-100 text-amber-800" };
  return { label: "your choice", tone: "bg-slate-100 text-slate-700" };
}

const rowId = (m: { dataset_id: number; layer: string }) => `${m.dataset_id}/${m.layer}`;

export default function AutoRecords({ domainId, onClose }: { domainId: number; onClose: () => void }) {
  const client = useQueryClient();
  const [mappings, setMappings] = useState<AutoMapping[] | null>(null);
  const [types, setTypes] = useState<string[]>([]);
  const [choices, setChoices] = useState<Record<string, AutoChoice>>({});
  const [busy, setBusy] = useState<"load" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [faults, setFaults] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState<AutoApplied | null>(null);
  const [naming, setNaming] = useState<{ id: string; draft: string } | null>(null);

  async function load(next: Record<string, AutoChoice>) {
    setBusy("load");
    setError(null);
    try {
      const proposal = await proposeDomainRecords(domainId, Object.values(next));
      setMappings(proposal.mappings);
      setTypes(proposal.types);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    void load({});
  }, [domainId]); // eslint-disable-line react-hooks/exhaustive-deps

  function choose(m: AutoMapping, change: Partial<AutoChoice>) {
    const id = rowId(m);
    const current: AutoChoice = choices[id] ?? { dataset_id: m.dataset_id, layer: m.layer, type: m.action === "skip" ? null : m.type };
    const next = { ...choices, [id]: { ...current, ...change } };
    setChoices(next);
    void load(next);
  }

  function edit(m: AutoMapping, change: Partial<AutoMapping>) {
    setMappings((all) => (all ?? []).map((x) => (rowId(x) === rowId(m) ? { ...x, ...change } : x)));
  }

  async function apply() {
    const chosen = (mappings ?? []).filter((m) => m.action !== "skip");
    setBusy("apply");
    setError(null);
    setFaults([]);
    try {
      const result = await applyDomainRecords(domainId, chosen);
      setDone(result);
      await client.invalidateQueries();
    } catch (e) {
      const raw = (e as Error).message ?? "";
      try {
        const detail = JSON.parse(raw).detail;
        setFaults(detail?.faults ?? []);
        setError(detail?.message ?? formatApiError(e));
      } catch {
        setError(formatApiError(e));
      }
    } finally {
      setBusy(null);
    }
  }

  const active = (mappings ?? []).filter((m) => m.action !== "skip");
  const totals = active.reduce((t, m) => ({ updates: t.updates + m.updates, creates: t.creates + (m.create_missing ? m.creates : 0) }),
    { updates: 0, creates: 0 });

  return (
    <section aria-label="Map data to records" className="rounded-lg border border-blue-200 bg-white shadow-sm">
      <header className="flex items-start gap-3 border-b border-slate-200 px-4 py-3">
        <Wand2 className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" aria-hidden />
        <div className="flex-1">
          <h2 className="font-semibold text-slate-900">Map data to records</h2>
          <p className="text-sm text-slate-600">
            Each layer is matched to the kind of record it belongs to: by record keys it shares with that kind, by name, and
            by fields. Features that name a record update it (its shape, measures and matched fields); the others become new
            records. Check it, change anything, then apply. Nothing is written before.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100">
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>

      {done ? (
        <div className="space-y-2 px-4 py-4 text-sm">
          <p className="flex items-center gap-2 font-medium text-emerald-800"><Check className="h-4 w-4" aria-hidden /> Done</p>
          <ul className="space-y-1">
            {done.results.map((r) => (
              <li key={`${r.dataset_id}/${r.layer}`}>
                <span className="text-slate-600">{r.layer}</span> →{" "}
                <Link className="font-medium text-blue-700 underline" to={`/domains/${domainId}/data/records?type=${r.entity_type_id}`}>
                  {r.type.replace(/_/g, " ")}
                </Link>
                : {r.updated} updated, {r.made} added
              </li>
            ))}
          </ul>
        </div>
      ) : mappings === null ? (
        <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Matching the layers to the kinds of record…
        </p>
      ) : mappings.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-500">No layer with features in this domain's map data.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Layer</th>
                  <th className="px-3 py-2">Kind of record</th>
                  <th className="px-3 py-2">Key</th>
                  <th className="px-3 py-2">What it does</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((m) => {
                  const id = rowId(m);
                  const c = confidence(m);
                  const fieldsOn = m.fields.filter((f) => !f.skip).length;
                  return [
                    <tr key={id} className={`border-t border-slate-100 align-top ${m.action === "skip" ? "opacity-60" : ""}`}>
                      <td className="px-3 py-2">
                        <p className="font-medium text-slate-900">{m.layer}</p>
                        <p className="text-xs text-slate-500">{m.dataset} · {m.features} features</p>
                      </td>
                      <td className="px-3 py-2">
                        <select
                          aria-label={`Kind of record for ${m.layer}`}
                          className="w-44 rounded border border-slate-300 bg-white px-2 py-1"
                          value={m.action === "skip" ? SKIP : types.includes(m.type) ? m.type : NEW}
                          disabled={busy !== null}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === SKIP) choose(m, { type: null });
                            else if (v === NEW) setNaming({ id, draft: types.includes(m.type) ? "" : m.type });
                            else choose(m, { type: v });
                          }}
                        >
                          {types.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
                          <option value={NEW}>{types.includes(m.type) ? "New kind…" : `New: ${m.type.replace(/_/g, " ")}`}</option>
                          <option value={SKIP}>Leave out</option>
                        </select>
                        {naming?.id === id && (
                          <form className="mt-1 flex gap-1" onSubmit={(e) => {
                            e.preventDefault();
                            if (naming.draft.trim()) choose(m, { type: naming.draft.trim() });
                            setNaming(null);
                          }}>
                            <input autoFocus aria-label="Name of the new kind of record" value={naming.draft}
                              onChange={(e) => setNaming({ id, draft: e.target.value })}
                              className="w-32 rounded border border-slate-300 px-2 py-0.5 text-xs" placeholder="e.g. parcel" />
                            <button type="submit" className="rounded bg-blue-600 px-2 text-xs text-white">OK</button>
                          </form>
                        )}
                        {m.action !== "skip" && (
                          <p className="mt-1 text-xs">
                            <span className={`rounded px-1.5 py-0.5 font-medium ${c.tone}`}>{c.label}</span>
                            {m.reasons.length > 0 && <span className="ms-1 text-slate-500">{m.reasons.join("; ")}</span>}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {m.action !== "skip" && (
                          <select
                            aria-label={`Key for ${m.layer}`}
                            className="w-36 rounded border border-slate-300 bg-white px-2 py-1"
                            value={m.key ?? ""}
                            disabled={busy !== null}
                            onChange={(e) => choose(m, { type: m.type, key: e.target.value || null })}
                          >
                            <option value="">numbered</option>
                            {Array.from(new Set([...(m.key ? [m.key] : []), ...m.key_candidates, ...m.fields.map((f) => f.property)]))
                              .map((k) => <option key={k} value={k}>{k}</option>)}
                          </select>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-700">
                        {m.action === "skip" ? "left out" : (
                          <>
                            <p>
                              {m.updates > 0 && <>updates <strong>{m.updates}</strong></>}
                              {m.updates > 0 && m.creates > 0 && " · "}
                              {m.creates > 0 && (m.create_missing ? <>adds <strong>{m.creates}</strong></> : <>{m.creates} not added</>)}
                            </p>
                            {m.creates > 0 && m.action === "existing" && (
                              <label className="mt-1 flex items-center gap-1.5 text-xs">
                                <input type="checkbox" checked={m.create_missing} disabled={m.required_unfilled.length > 0}
                                  onChange={(e) => edit(m, { create_missing: e.target.checked })} />
                                add the {m.creates} the kind does not have yet
                              </label>
                            )}
                            {m.required_unfilled.length > 0 && (
                              <p className="text-xs text-amber-800">Required, with nothing to fill it: {m.required_unfilled.join(", ")}</p>
                            )}
                            <button type="button" onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id}
                              className="mt-1 inline-flex items-center gap-1 text-xs text-blue-700 hover:underline">
                              {open === id ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3 rtl:rotate-180" aria-hidden />}
                              {fieldsOn} field{fieldsOn === 1 ? "" : "s"} + shape in “{m.geometry_field}”
                            </button>
                            {m.faults.length > 0 && (
                              <p className="mt-1 flex gap-1 text-xs text-red-700"><AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                                {m.faults.length} value{m.faults.length === 1 ? "" : "s"} would not fit: {m.faults[0]}</p>
                            )}
                          </>
                        )}
                      </td>
                    </tr>,
                    open === id && m.action !== "skip" ? (
                      <tr key={`${id}-fields`} className="bg-slate-50">
                        <td colSpan={4} className="px-3 py-2">
                          <ul className="grid gap-1 sm:grid-cols-2">
                            {m.fields.map((f) => (
                              <li key={f.property} className="flex items-center gap-2 text-xs">
                                <input type="checkbox" aria-label={`Use ${f.property}`} checked={!f.skip}
                                  onChange={(e) => edit(m, { fields: m.fields.map((x) => (x.property === f.property ? { ...x, skip: !e.target.checked } : x)) })} />
                                <span className="font-mono">{f.property}</span> →
                                <span className={f.new ? "text-sky-800" : "text-slate-900"}>
                                  {f.name} <span className="text-slate-500">({f.data_type}{f.new ? ", new field" : ""})</span>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
          {error && (
            <div role="alert" className="mx-4 mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-800">
              <p>{error}</p>
              {faults.length > 0 && <ul className="mt-1 list-disc ps-5 text-xs">{faults.slice(0, 10).map((f) => <li key={f}>{f}</li>)}</ul>}
            </div>
          )}
          <footer className="flex flex-wrap items-center gap-3 px-4 py-3">
            <button type="button" onClick={() => void apply()} disabled={busy !== null || active.length === 0}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {busy === "apply" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Check className="h-4 w-4" aria-hidden />}
              Apply to {active.length} layer{active.length === 1 ? "" : "s"}
            </button>
            <span className="text-sm text-slate-600">{totals.updates} records updated, {totals.creates} added</span>
            {busy === "load" && <span className="flex items-center gap-1 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" aria-hidden /> mapping again…</span>}
          </footer>
        </>
      )}
      {error && mappings === null && <p role="alert" className="px-4 pb-4 text-sm text-red-700">{error}</p>}
    </section>
  );
}
