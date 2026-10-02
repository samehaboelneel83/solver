import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useDataset, useDatasets } from "../api/gis";
import {
  useComputeDistances, useComputeSpatial, useComputeWithin,
  type ComputedSource, type EntityType, type Id, type Metric, type NetworkSource,
} from "../api/v1";
import { useToast } from "./ToastProvider";
import { useEditorLevel } from "../model/editorLevel";
import { formatApiError } from "../api/errors";

/**
 * Data computed from the map (queue R16a; improvement plan, phase 2): between
 * kinds of record whose records have a shape. Each result is ordinary data --
 * a parameter, a field or a relationship -- with how it was made recorded, so
 * a model reads it like anything typed in:
 *
 * - distance or travel time `name[from, to]`, in a straight line, along the
 *   map tiles' roads, or along a lines layer the person imported;
 * - within a reach: a relationship, or a 0/1 parameter a rule multiplies by;
 * - which area each place is in; how many places lie within a distance;
 *   the nearest few; areas sharing a border; the area two shapes share.
 *
 * Only kinds with a geometry field are offered; computing again replaces.
 */
type Make = "distances" | "within" | "within_flag" | "inside" | "crosses" | "count" | "nearest" | "touching" | "overlap" | "elevation";

const MAKES: [Make, string, string][] = [
  ["distances", "a distance or travel-time parameter", "distance"],
  ["within", "a within relationship", "within_reach"],
  ["within_flag", "a 0/1 within parameter (for rules)", "reach"],
  ["inside", "which area each place is in (a link)", "area_of"],
  ["crosses", "the areas each line passes through (links, with metres)", "passes_through"],
  ["count", "how many lie within a distance (a field)", "near_count"],
  ["nearest", "links to the nearest few", "nearest"],
  ["touching", "links between areas sharing a border", "next_to"],
  ["overlap", "the area two kinds share (m², a parameter)", "overlap_m2"],
  ["elevation", "ground height and slope of each place (fields)", "ground_m"],
];

const MEASURED = new Set<Make>(["distances", "within", "within_flag"]);

/** Where each result is kept, so the line that reports it can take the person there. */
export function resultPlace(kind: Make, domainId: Id, simple = false): { to: string; words: string; read: string } {
  if (kind === "distances" || kind === "within_flag" || kind === "overlap")
    return { to: `/domains/${domainId}/data/parameters`, words: `Open it under ${simple ? "Data values" : "Parameters"}`,
      read: "a model reads it once it is ticked under “Data this model reads”" };
  if (kind === "count" || kind === "elevation")
    return { to: `/domains/${domainId}/data/records`, words: "See it on the records", read: "a model reads it as a field of each record" };
  // Simple has no Relationships page: the workbench shows each record's links.
  return simple
    ? { to: `/domains/${domainId}/data/workbench`, words: "See the links in the Data workbench", read: "a model walks them from either end" }
    : { to: `/domains/${domainId}/data/relationships`, words: "See the links under Relationships", read: "a model walks them from either end" };
}

export default function MeasureFromMap({ domainId, entityTypes }: { domainId: Id; entityTypes: EntityType[] }) {
  const id = useId();
  const placed = entityTypes.filter((t) => t.attributes.some((a) => a.data_type === "geometry"));
  const [kind, setKind] = useState<Make>("distances");
  const [name, setName] = useState("distance");
  const [named, setNamed] = useState(false);
  const [from, setFrom] = useState<Id | "">(placed[0]?.id ?? "");
  const [to, setTo] = useState<Id | "">(placed[1]?.id ?? placed[0]?.id ?? "");
  const [metric, setMetric] = useState<Metric>("straight");
  const [unit, setUnit] = useState<"m" | "km" | "s" | "min">("m");
  const [nearest, setNearest] = useState("");
  const [km, setKm] = useState("5");
  const [minutes, setMinutes] = useState("15");
  const [radius, setRadius] = useState("300");
  const [k, setK] = useState("3");
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [layer, setLayer] = useState("");
  const [speedField, setSpeedField] = useState("");
  const [defaultKmh, setDefaultKmh] = useState("30");
  const [joinM, setJoinM] = useState("500");
  const [closedField, setClosedField] = useState("");
  const [delayField, setDelayField] = useState("");
  const [avoidKind, setAvoidKind] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  // Kept on screen (a toast fades): places a travel time could not reach, and why.
  const [notice, setNotice] = useState<string | null>(null);
  // The last result, kept on screen with where it went: a toast alone is easy to miss.
  const [last, setLast] = useState<{ text: string; kind: Make } | null>(null);
  const distances = useComputeDistances();
  const within = useComputeWithin();
  const spatial = useComputeSpatial();
  const toast = useToast();
  const [level] = useEditorLevel();
  const simple = level === "simple";
  const timed = metric === "time" || metric === "network_time";
  const onLayer = metric === "network" || metric === "network_time";
  // Read only when a layer is to be travelled along: the form otherwise asks nothing of the server.
  const datasets = useDatasets(onLayer ? (domainId as number) : null);
  const chosenDataset = datasetId ?? datasets.data?.items?.[0]?.id ?? null;
  const dataset = useDataset(onLayer ? chosenDataset : null);
  const lineLayers = (dataset.data?.layers ?? []).filter((l) => (l.kinds?.line ?? 0) > 0);
  const busy = distances.isPending || within.isPending || spatial.isPending;

  if (placed.length === 0) return null;

  function network(): NetworkSource | null {
    const chosenLayer = layer || lineLayers[0]?.name || "";
    if (!chosenDataset || !chosenLayer) return null;
    const speed = Number(defaultKmh);
    return {
      dataset_id: chosenDataset, layer: chosenLayer,
      ...(speedField.trim() ? { speed_field: speedField.trim() } : {}),
      ...(speed > 0 && speed !== 30 ? { default_kmh: speed } : {}),
      ...(Number(joinM) > 0 && Number(joinM) !== 500 ? { join_m: Number(joinM) } : {}),
      ...(closedField.trim() ? { closed_field: closedField.trim() } : {}),
      ...(delayField.trim() ? { delay_field: delayField.trim() } : {}),
      ...(avoidKind ? { avoid_type_id: Number(avoidKind) } : {}),
    };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setLast(null);
    const report = (text: string) => {
      toast.success(text);
      setLast({ text, kind });
    };
    if (!/^[a-z][a-z0-9_]*$/.test(name)) return setError("A name is lower case letters, digits and _, starting with a letter.");
    if (from === "" || (kind !== "touching" && kind !== "elevation" && to === "")) return setError("Choose both kinds.");
    const fromId = from as Id;
    const toId = (to === "" ? from : to) as Id;
    // Said here rather than as the server's validation text (benchmark, October 2026).
    if (onLayer && Number(joinM) > 20000) return setError("Join places up to: at most 20,000 m (20 km). A place further from every line is left out and named.");
    const net = onLayer ? network() : null;
    if (onLayer && !net) return setError("Choose imported map data with a lines layer to travel along.");
    const along = net ? { network: net } : {};
    try {
      if (kind === "distances") {
        const keep = nearest.trim() === "" ? undefined : Number(nearest);
        if (keep !== undefined && !(Number.isInteger(keep) && keep >= 1)) return setError("Keep the nearest: a whole number, 1 or more, or blank for all.");
        const done = await distances.mutateAsync({ domainId, name, from_type_id: fromId, to_type_id: toId, metric, unit, ...(keep ? { nearest: keep } : {}), ...along });
        report(`${name}: ${done.pairs.toLocaleString("en-US")} ${timed ? "travel times" : "distances"} computed${done.missing.length ? `; ${done.missing.length} without a shape left out` : ""}`);
        setNotice(leftOut(done.source, Number(joinM) || 500));
      } else if (kind === "within" || kind === "within_flag") {
        const max = Number(timed ? minutes : km);
        if (!(max > 0)) return setError(timed ? "Within: a time above 0 minutes." : "Within: a distance above 0 km.");
        const reach = timed ? { max_min: max } : { max_m: max * 1000 };
        const done = await within.mutateAsync({
          domainId, name, from_type_id: fromId, to_type_id: toId, metric, ...reach, ...along,
          ...(kind === "within_flag" ? { output: "parameter" as const } : {}),
        });
        report(`${name}: ${done.edges.toLocaleString("en-US")} pairs within ${max} ${timed ? "min" : "km"} ${kind === "within_flag" ? "marked 1" : "linked"}`);
        setNotice(leftOut(done.source, Number(joinM) || 500));
      } else if (kind === "elevation") {
        const done = await spatial.mutateAsync({ domainId, op: "elevation", name, type_id: fromId });
        const off = done.uncovered?.length ? `; ${done.uncovered.length} outside the terrain tiles` : "";
        report(`${name} and ${done.slope_field ?? `${name}_slope`}: set on ${done.records ?? 0} records${off}`);
      } else if (kind === "touching") {
        const done = await spatial.mutateAsync({ domainId, op: "touching", name, type_id: fromId });
        report(`${name}: ${done.links ?? 0} links between areas sharing a border`);
      } else if (kind === "count") {
        const metres = Number(radius);
        if (!(metres > 0)) return setError("Count within: a distance above 0 metres.");
        const done = await spatial.mutateAsync({ domainId, op: "count", name, from_type_id: fromId, to_type_id: toId, max_m: metres });
        report(`${name}: counted for ${done.records ?? 0} records, ${done.with_any ?? 0} with at least one within ${metres} m`);
      } else if (kind === "nearest") {
        const many = Number(k);
        if (!(Number.isInteger(many) && many >= 1 && many <= 50)) return setError("Nearest: a whole number from 1 to 50.");
        const done = await spatial.mutateAsync({ domainId, op: "nearest", name, from_type_id: fromId, to_type_id: toId, k: many });
        report(`${name}: ${done.links ?? 0} links to the nearest ${many}`);
      } else {
        const done = await spatial.mutateAsync({ domainId, op: kind, name, from_type_id: fromId, to_type_id: toId });
        const outside = done.outside?.length ? `; ${done.outside.length} in no area` : "";
        report(kind === "inside" ? `${name}: ${done.links ?? 0} places linked to their area${outside}`
          : kind === "crosses" ? `${name}: ${done.links ?? 0} links from lines to the areas they pass through`
          : `${name}: ${done.pairs ?? 0} overlapping pairs`);
      }
    } catch (err) {
      setError(formatApiError(err));
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
  const fromLabel = kind === "crosses" ? "Lines" : kind === "inside" ? "Places" : kind === "elevation" ? "Places" : kind === "touching" ? "Areas" : kind === "count" ? "For each" : "From";
  const toLabel = kind === "inside" || kind === "crosses" ? "Areas" : kind === "count" ? "Count" : "To";

  return (
    <section aria-labelledby={`${id}-heading`} className="mb-6 rounded-md border border-slate-200 bg-white p-4">
      <h2 id={`${id}-heading`} className="mb-1 text-base font-semibold text-slate-900">Compute from the map</h2>
      <p className="mb-3 text-sm text-slate-600">
        From records that have a shape: distances and travel times (a straight line, the map's roads, or a lines layer
        you imported, with its own speeds), what is within reach, which area each place is in, what is near, what touches.
        The result is ordinary data a model reads — and it remembers how it was made.
      </p>
      <form aria-label="Compute from the map" onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`${id}-kind`} className="block text-xs text-slate-600">Make</label>
          <select id={`${id}-kind`} className="rounded border px-2 py-1 text-sm" value={kind}
                  onChange={(event) => {
                    const next = event.target.value as Make;
                    setKind(next);
                    // A name the person typed stays; only the suggested one follows the choice
                    // (benchmark, October 2026: typed names became "area_of" and "distance").
                    if (!named) setName(MAKES.find(([value]) => value === next)?.[2] ?? "result");
                    // Operations on areas start from a kind that looks like areas, not the first kind with a shape.
                    const area = areaKinds(placed)[0];
                    if (area && (next === "inside" || next === "crosses" || next === "overlap") && !areaKinds(placed).some((t) => t.id === to)) setTo(area.id);
                    if (area && next === "touching" && !areaKinds(placed).some((t) => t.id === from)) setFrom(area.id);
                  }}>
            {MAKES.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-name`} className="block text-xs text-slate-600">Name</label>
          <input id={`${id}-name`} className="rounded border px-2 py-1 font-mono text-sm" value={name}
                 onChange={(event) => { setName(event.target.value); setNamed(event.target.value.trim() !== ""); }} />
        </div>
        {MEASURED.has(kind) && (
          <div>
            <label htmlFor={`${id}-metric`} className="block text-xs text-slate-600">Measured</label>
            <select id={`${id}-metric`} className="rounded border px-2 py-1 text-sm" value={metric}
                    onChange={(event) => {
                      const next = event.target.value as Metric;
                      setMetric(next);
                      setUnit(next === "time" || next === "network_time" ? "min" : "m");
                    }}>
              <option value="straight">in a straight line</option>
              <option value="road">along the roads</option>
              <option value="time">as road travel time</option>
              <option value="network">along a lines layer I imported</option>
              <option value="network_time">as travel time along a lines layer I imported</option>
            </select>
          </div>
        )}
        {typeSelect(fromLabel, from, setFrom)}
        {kind !== "touching" && kind !== "elevation" && typeSelect(toLabel, to, setTo)}
        {MEASURED.has(kind) && onLayer && (
          <>
            <div>
              <label htmlFor={`${id}-dataset`} className="block text-xs text-slate-600">Map data</label>
              <select id={`${id}-dataset`} className="rounded border px-2 py-1 text-sm" value={chosenDataset ?? ""}
                      onChange={(event) => { setDatasetId(Number(event.target.value)); setLayer(""); }}>
                {datasets.data?.items?.length === 0 && <option value="">no map data in this workspace</option>}
                {(datasets.data?.items ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor={`${id}-layer`} className="block text-xs text-slate-600">Lines layer</label>
              <select id={`${id}-layer`} className="rounded border px-2 py-1 text-sm" value={layer || lineLayers[0]?.name || ""}
                      onChange={(event) => setLayer(event.target.value)}>
                {lineLayers.length === 0 && <option value="">no lines in this map data</option>}
                {lineLayers.map((l) => <option key={l.id} value={l.name}>{l.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor={`${id}-speed`} className="block text-xs text-slate-600">Speed field (km/h, optional)</label>
              <input id={`${id}-speed`} className="w-28 rounded border px-2 py-1 font-mono text-sm" placeholder="speed_kmh" value={speedField}
                     onChange={(event) => setSpeedField(event.target.value)} />
            </div>
            <div>
              <label htmlFor={`${id}-kmh`} className="block text-xs text-slate-600">Otherwise (km/h)</label>
              <input id={`${id}-kmh`} className="w-20 rounded border px-2 py-1 text-sm" inputMode="decimal" value={defaultKmh}
                     onChange={(event) => setDefaultKmh(event.target.value)} />
            </div>
            <div>
              <label htmlFor={`${id}-join`} className="block text-xs text-slate-600">Join places up to (m, at most 20,000)</label>
              <input id={`${id}-join`} className="w-20 rounded border px-2 py-1 text-sm" inputMode="decimal" value={joinM}
                     title="A place further than this from every line cannot join the network; its pairs are left out and named."
                     onChange={(event) => setJoinM(event.target.value)} />
            </div>
            <div>
              <label htmlFor={`${id}-closed`} className="block text-xs text-slate-600">Closed when (a field, optional)</label>
              <input id={`${id}-closed`} className="w-28 rounded border px-2 py-1 font-mono text-sm" placeholder="flooded" value={closedField}
                     title="A line whose field is yes, true, 1 or “closed” is left out: a flooded or blocked road."
                     onChange={(event) => setClosedField(event.target.value)} />
            </div>
            <div>
              <label htmlFor={`${id}-delay`} className="block text-xs text-slate-600">Delay (minutes field, optional)</label>
              <input id={`${id}-delay`} className="w-28 rounded border px-2 py-1 font-mono text-sm" placeholder="delay_min" value={delayField}
                     title="Minutes added to travel along the whole line: a checkpoint, roadworks."
                     onChange={(event) => setDelayField(event.target.value)} />
            </div>
            <div>
              <label htmlFor={`${id}-avoid`} className="block text-xs text-slate-600">Never through (areas, optional)</label>
              <select id={`${id}-avoid`} className="rounded border px-2 py-1 text-sm" value={avoidKind} onChange={(event) => setAvoidKind(event.target.value)}>
                <option value="">nothing</option>
                {areaKinds(placed).map((t) => <option key={t.id} value={String(t.id)}>{t.name}</option>)}
              </select>
            </div>
          </>
        )}
        {kind === "distances" && (
          <>
            <div>
              <label htmlFor={`${id}-unit`} className="block text-xs text-slate-600">In</label>
              <select id={`${id}-unit`} className="rounded border px-2 py-1 text-sm" value={unit}
                      onChange={(event) => setUnit(event.target.value as "m" | "km" | "s" | "min")}>
                {timed ? (
                  <>
                    <option value="min">minutes</option>
                    <option value="s">whole seconds</option>
                  </>
                ) : (
                  <>
                    <option value="m">whole metres</option>
                    <option value="km">kilometres</option>
                  </>
                )}
              </select>
            </div>
            <div>
              <label htmlFor={`${id}-nearest`} className="block text-xs text-slate-600">Keep only the nearest (blank: all)</label>
              <input id={`${id}-nearest`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="numeric" value={nearest}
                     onChange={(event) => setNearest(event.target.value)} />
            </div>
          </>
        )}
        {(kind === "within" || kind === "within_flag") && (timed ? (
          <div>
            <label htmlFor={`${id}-min`} className="block text-xs text-slate-600">Within (minutes)</label>
            <input id={`${id}-min`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="decimal" value={minutes}
                   onChange={(event) => setMinutes(event.target.value)} />
          </div>
        ) : (
          <div>
            <label htmlFor={`${id}-km`} className="block text-xs text-slate-600">Within (km)</label>
            <input id={`${id}-km`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="decimal" value={km}
                   onChange={(event) => setKm(event.target.value)} />
            {Number(km) >= 100 && (
              <p className="mt-1 max-w-[16rem] text-xs text-amber-800">
                That is {Number(km).toLocaleString("en-US")} km — did you mean {Number(km) / 1000} km ({Number(km).toLocaleString("en-US")} m)?
              </p>
            )}
          </div>
        ))}
        {kind === "count" && (
          <div>
            <label htmlFor={`${id}-radius`} className="block text-xs text-slate-600">Within (metres)</label>
            <input id={`${id}-radius`} className="w-24 rounded border px-2 py-1 text-sm" inputMode="decimal" value={radius}
                   onChange={(event) => setRadius(event.target.value)} />
          </div>
        )}
        {kind === "nearest" && (
          <div>
            <label htmlFor={`${id}-k`} className="block text-xs text-slate-600">How many</label>
            <input id={`${id}-k`} className="w-16 rounded border px-2 py-1 text-sm" inputMode="numeric" value={k}
                   onChange={(event) => setK(event.target.value)} />
          </div>
        )}
        <button type="submit" disabled={busy}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60">
          {busy ? "Computing…" : "Compute"}
        </button>
      </form>
      {kind === "within_flag" && (
        <p className="mt-2 text-xs text-slate-600">
          1 where the pair is within reach, else 0 — so a rule can say{" "}
          <code className="font-mono">sum(reach[y, h] * open[y] for y in yard) &gt;= 1</code>.
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
      {last && (
        <p role="status" className="mt-2 rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-sm text-emerald-900">
          ✓ {last.text}.{" "}
          <Link className="font-medium underline" to={resultPlace(last.kind, domainId, simple).to}>{resultPlace(last.kind, domainId, simple).words}</Link>
          {" "}— {resultPlace(last.kind, domainId, simple).read}.
        </p>
      )}
      {notice && <p role="status" className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-sm text-amber-900">{notice}</p>}
    </section>
  );
}

/** What a travel computation could not reach, in words -- or null when it reached everything. */
export function leftOut(source: ComputedSource | undefined, joinM: number): string | null {
  const off = source?.off_network ?? [];
  const offRoad = source?.off_road ?? [];
  const parts: string[] = [];
  if (off.length) {
    parts.push(`${off.length} place${off.length > 1 ? "s are" : " is"} further than ${joinM} m from every line, so ${off.length > 1 ? "their" : "its"} pairs were left out: ${off.slice(0, 8).join(", ")}${off.length > 8 ? ` and ${off.length - 8} more` : ""}. Widen “Join places up to” to bring ${off.length > 1 ? "them" : "it"} in.`);
  }
  if (offRoad.length) parts.push(`${offRoad.length} too far from any road: ${offRoad.slice(0, 8).join(", ")}${offRoad.length > 8 ? ` and ${offRoad.length - 8} more` : ""}.`);
  if (source?.no_road) parts.push(`${source.no_road} pairs have no road between them.`);
  return parts.length ? parts.join(" ") : null;
}

/** Kinds whose records are most likely areas: a measured area_m2 (Make records writes it for polygons),
 * else a name like district, zone, area, region -- best first. */
export function areaKinds(kinds: EntityType[]): EntityType[] {
  const score = (t: EntityType) =>
    (t.attributes.some((a) => /^area(_m2|_km2)?$/i.test(a.name)) ? 2 : 0) +
    (/district|zone|area|region|ward|polygon|parcel|block|sector|governorate|neighbou?rhood/i.test(t.name) ? 1 : 0);
  return kinds.filter((t) => score(t) > 0).sort((a, b) => score(b) - score(a));
}
