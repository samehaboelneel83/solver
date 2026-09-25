import { useId, useState, type FormEvent } from "react";
import { useComputeDistances, useComputeWithin, type EntityType, type Id } from "../api/v1";
import { useToast } from "./ToastProvider";

/**
 * Distances and nearness computed from the map (queue R16a): between two
 * entity types whose records have a shape, straight-line (geodesic), into a
 * parameter `name[from, to]` -- or, as `within`, a relationship linking each
 * pair closer than a distance. Only types with a geometry attribute are
 * offered; computing again replaces what was there.
 */
export default function MeasureFromMap({ domainId, entityTypes }: { domainId: Id; entityTypes: EntityType[] }) {
  const id = useId();
  const placed = entityTypes.filter((t) => t.attributes.some((a) => a.data_type === "geometry"));
  const [kind, setKind] = useState<"distances" | "within">("distances");
  const [name, setName] = useState("distance");
  const [from, setFrom] = useState<Id | "">(placed[0]?.id ?? "");
  const [to, setTo] = useState<Id | "">(placed[1]?.id ?? placed[0]?.id ?? "");
  const [unit, setUnit] = useState<"m" | "km">("m");
  const [nearest, setNearest] = useState("");
  const [km, setKm] = useState("5");
  const [error, setError] = useState<string | null>(null);
  const distances = useComputeDistances();
  const within = useComputeWithin();
  const toast = useToast();
  const busy = distances.isPending || within.isPending;

  if (placed.length === 0) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^[a-z][a-z0-9_]*$/.test(name)) return setError("A name is lower case letters, digits and _, starting with a letter.");
    if (from === "" || to === "") return setError("Choose both types.");
    try {
      if (kind === "distances") {
        const k = nearest.trim() === "" ? undefined : Number(nearest);
        if (k !== undefined && !(Number.isInteger(k) && k >= 1)) return setError("Keep the nearest: a whole number, 1 or more, or blank for all.");
        const done = await distances.mutateAsync({ domainId, name, from_type_id: from, to_type_id: to, unit, ...(k ? { nearest: k } : {}) });
        toast.success(`${name}: ${done.pairs.toLocaleString()} distances computed${done.missing.length ? `; ${done.missing.length} without a shape left out` : ""}`);
      } else {
        const max = Number(km);
        if (!(max > 0)) return setError("Within: a distance above 0 km.");
        const done = await within.mutateAsync({ domainId, name, from_type_id: from, to_type_id: to, max_m: max * 1000 });
        toast.success(`${name}: ${done.edges.toLocaleString()} pairs within ${max} km linked`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const typeSelect = (label: string, value: Id | "", set: (v: Id) => void) => (
    <div>
      <label htmlFor={`${id}-${label}`} className="block text-xs text-slate-600">{label}</label>
      <select id={`${id}-${label}`} className="rounded border px-2 py-1 text-sm" value={value}
              onChange={(event) => set(Number(event.target.value) as Id)}>
        {placed.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
    </div>
  );

  return (
    <section aria-labelledby={`${id}-heading`} className="mb-6 rounded-md border border-slate-200 bg-white p-4">
      <h2 id={`${id}-heading`} className="mb-1 text-base font-semibold text-slate-900">Compute from the map</h2>
      <p className="mb-3 text-sm text-slate-600">
        Straight-line distances between places with a shape -- a floor on road distance, not an estimate of it.
      </p>
      <form aria-label="Compute from the map" onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`${id}-kind`} className="block text-xs text-slate-600">Make</label>
          <select id={`${id}-kind`} className="rounded border px-2 py-1 text-sm" value={kind}
                  onChange={(event) => {
                    const next = event.target.value as "distances" | "within";
                    setKind(next);
                    setName(next === "distances" ? "distance" : "within_reach");
                  }}>
            <option value="distances">a distance parameter</option>
            <option value="within">a within relationship</option>
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-name`} className="block text-xs text-slate-600">Name</label>
          <input id={`${id}-name`} className="rounded border px-2 py-1 font-mono text-sm" value={name}
                 onChange={(event) => setName(event.target.value)} />
        </div>
        {typeSelect("From", from, setFrom)}
        {typeSelect("To", to, setTo)}
        {kind === "distances" ? (
          <>
            <div>
              <label htmlFor={`${id}-unit`} className="block text-xs text-slate-600">In</label>
              <select id={`${id}-unit`} className="rounded border px-2 py-1 text-sm" value={unit}
                      onChange={(event) => setUnit(event.target.value as "m" | "km")}>
                <option value="m">whole metres</option>
                <option value="km">kilometres</option>
              </select>
            </div>
            <div>
              <label htmlFor={`${id}-nearest`} className="block text-xs text-slate-600">Keep only the nearest (blank: all)</label>
              <input id={`${id}-nearest`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="numeric" value={nearest}
                     onChange={(event) => setNearest(event.target.value)} />
            </div>
          </>
        ) : (
          <div>
            <label htmlFor={`${id}-km`} className="block text-xs text-slate-600">Within (km)</label>
            <input id={`${id}-km`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="decimal" value={km}
                   onChange={(event) => setKm(event.target.value)} />
          </div>
        )}
        <button type="submit" disabled={busy}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60">
          {busy ? "Computing…" : "Compute"}
        </button>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
    </section>
  );
}
