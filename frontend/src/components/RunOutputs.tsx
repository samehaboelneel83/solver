/**
 * What a run's answer becomes outside the run page (improvement plan, phase 3):
 *
 * - **on the map** -- any run whose sets have shapes: the places a decision
 *   chose, the links it made, the places a rule fell short at (3.1);
 * - **downloads** -- Excel (a sheet per decision, the rules), CSV, GeoJSON, a printable report (3.2);
 * - **compared** -- two answers on one map, only what changed (3.4, `CompareMap`);
 * - **kept as data** -- one decision written into the workspace as a
 *   relationship or a parameter, so the next problem can read it (3.5).
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiFetch } from "../api/client";
import { downloadFrom } from "../api/camps";
import { formatApiError } from "../api/errors";
import { BASEMAP_STORAGE_KEY, useBasemaps } from "../hooks/useBasemaps";
import type { Id } from "../api/v1";
import GeoMap, { rampColour, type GeoGeometry, type GeoMark } from "./map/GeoMap";
import { getDataset, getFeatures, useDatasets } from "../api/gis";
import { useDomain } from "../hooks/useDomain";

type AnswerFeature = {
  geometry: GeoGeometry;
  properties: {
    layer: string; key: string; label?: string; status: "chosen" | "not_chosen" | "short" | "place"; title: string; value: unknown;
    /** The place's number fields, to colour areas by (population, vulnerability). */
    data?: Record<string, number>;
  };
};
export type AnswerMap = { none?: string; layers: { id: string; kind: string; title: string }[]; features: AnswerFeature[]; truncated?: boolean };

const COLOURS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#4f46e5"];
const SHORT = "#dc2626";
const QUIET = "#94a3b8";
const CONTEXT = "#475569";

const CHANGE: Record<string, string> = { added: "#059669", removed: "#dc2626", same: "#94a3b8", short: "#dc2626", fixed: "#059669" };

/** Two answers on one map: what one run chose that the other did not (improvement plan 3.4). */
export function CompareMap({ left, right }: { left: Id; right: Id }) {
  const map = useQuery({
    queryKey: ["answer-map-compare", left, right],
    queryFn: () => apiFetch<AnswerMap & { changed?: number }>(`/api/v1/runs/${left}/answer-map/compare/${right}`),
    retry: false,
  });
  if (!map.data || map.data.none || !Array.isArray(map.data.features) || !map.data.features.length) return null;
  const marks = map.data.features.map((f, i) => {
    const s = f.properties.status as string;
    return {
      id: `${f.properties.layer}:${f.properties.key}:${i}`, geometry: f.geometry, colour: CHANGE[s] ?? QUIET,
      layer: f.properties.layer, title: f.properties.title,
      label: s === "same" ? undefined : f.properties.label ?? f.properties.key,
      size: f.geometry.type.includes("Line") ? 2 : s === "same" ? 4 : 7, fill: s === "same" ? 0.1 : 0.4,
    } satisfies GeoMark;
  });
  const legend = [
    { layer: "added", colour: CHANGE.added, text: `chosen in run ${String(left)}, not in ${String(right)} (or no longer short)` },
    { layer: "removed", colour: CHANGE.removed, text: `chosen in run ${String(right)} only (or newly short)` },
    { layer: "same", colour: CHANGE.same, text: "the same in both" },
  ];
  return (
    <section aria-label="Comparison on the map" className="mt-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-900">
        On the map: {map.data.changed ?? 0} {map.data.changed === 1 ? "change" : "changes"} from run {String(right)} to run {String(left)}
      </h3>
      <GeoMap marks={marks} legend={legend} caption={map.data.layers.map((l) => l.title).join(" · ")} />
    </section>
  );
}

export function marksOf(map: AnswerMap): { marks: GeoMark[]; legend: { layer: string; colour: string; text: string }[] } {
  const colourOf = new Map<string, string>();
  map.layers.forEach((layer, i) => {
    colourOf.set(layer.id, layer.kind === "unmet" ? SHORT : layer.kind === "context" ? CONTEXT : COLOURS[i % COLOURS.length]);
  });
  const marks = map.features.map((f, i) => {
    const p = f.properties;
    const base = colourOf.get(p.layer) ?? CONTEXT;
    const colour = p.status === "short" ? SHORT : p.status === "not_chosen" ? QUIET : base;
    return {
      id: `${p.layer}:${p.key}:${i}`, geometry: f.geometry, colour, layer: p.layer, title: p.title,
      label: p.status === "chosen" || p.status === "short" ? p.label ?? p.key : undefined,
      size: f.geometry.type.includes("Line") ? 2 : p.status === "short" ? 8 : p.status === "chosen" ? 6 : 4,
      fill: p.status === "chosen" ? 0.4 : 0.15,
    } satisfies GeoMark;
  });
  const legend = map.layers.map((l) => ({ layer: l.id, colour: colourOf.get(l.id) ?? CONTEXT, text: l.title }));
  return { marks, legend };
}

const isArea = (g: GeoGeometry) => g.type === "Polygon" || g.type === "MultiPolygon";

/** The number fields the areas on an answer map carry: what they may be coloured by. */
export function areaFields(map: AnswerMap): string[] {
  const names = new Set<string>();
  for (const f of map.features) if (isArea(f.geometry)) Object.keys(f.properties.data ?? {}).forEach((k) => names.add(k));
  return [...names].sort();
}

/** Areas filled by a number on a scale (user trial: which covered zones are the vulnerable ones?). The
 * answer still shows: a chosen area is filled deeper than one that is not. */
export function colourAreas(map: AnswerMap, marks: GeoMark[], field: string): { marks: GeoMark[]; ramp: { title: string; min: number; max: number } | null } {
  const values = map.features.filter((f) => isArea(f.geometry)).map((f) => f.properties.data?.[field]).filter((v): v is number => typeof v === "number");
  if (!values.length) return { marks, ramp: null };
  const min = Math.min(...values), max = Math.max(...values);
  const out = marks.map((m, i) => {
    const f = map.features[i];
    const v = f && isArea(f.geometry) ? f.properties.data?.[field] : undefined;
    if (typeof v !== "number") return m;
    const chosen = f.properties.status === "chosen";
    return { ...m, colour: rampColour(max > min ? (v - min) / (max - min) : 1), fill: chosen ? 0.75 : 0.3,
      title: `${m.title} · ${field} ${v.toLocaleString("en-US")}` };
  });
  return { marks: out, ramp: { title: field, min, max } };
}

function KeepAsData({ runId, decisions }: { runId: Id; decisions: [string, { index?: string[]; domain?: string }][] }) {
  const client = useQueryClient();
  const [decision, setDecision] = useState(decisions[0]?.[0] ?? "");
  const spec = decisions.find(([name]) => name === decision)?.[1];
  const linkable = (spec?.index?.length ?? 0) === 2 && (spec?.domain ?? "binary") === "binary";
  const [as, setAs] = useState<"relationship" | "parameter">("parameter");
  const [name, setName] = useState("");
  const [follow, setFollow] = useState(true);
  const [said, setSaid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const kind = linkable ? as : "parameter";
  async function keep() {
    setBusy(true);
    setSaid(null);
    try {
      const done = await apiFetch<{ links?: number; cells?: number; left_out: string[] }>(`/api/v1/runs/${runId}/promote`, {
        method: "POST", body: JSON.stringify({ decision, name: name || `${decision}_plan`, as: kind, follow }),
      });
      void client.invalidateQueries();
      setSaid(`Kept as ${kind} ${name || `${decision}_plan`}: ${done.links ?? done.cells ?? 0} ${kind === "relationship" ? "links" : "values"}.`
        + (follow ? " It will be rewritten whenever another plan of this problem is approved." : ""));
    } catch (e) {
      setSaid(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }
  if (!decisions.length) return null;
  return (
    <div className="flex flex-wrap items-end gap-2 text-sm">
      <label className="text-xs text-slate-600">Keep
        <select aria-label="Decision to keep" className="ml-1 rounded border px-2 py-1 text-sm" value={decision} onChange={(e) => setDecision(e.target.value)}>
          {decisions.map(([n]) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <label className="text-xs text-slate-600">as
        <select aria-label="Keep it as" className="ml-1 rounded border px-2 py-1 text-sm" value={kind} disabled={!linkable}
          onChange={(e) => setAs(e.target.value as "relationship" | "parameter")}>
          <option value="parameter">data values (a parameter)</option>
          {linkable && <option value="relationship">links between records</option>}
        </select>
      </label>
      <label className="text-xs text-slate-600">named
        <input aria-label="Name of the kept data" className="ml-1 w-36 rounded border px-2 py-1 font-mono text-sm" placeholder={`${decision}_plan`}
          value={name} onChange={(e) => setName(e.target.value.trim())} />
      </label>
      <label className="text-xs text-slate-600" title="Other problems that read it then always plan on the approved answer (a chain).">
        <input type="checkbox" className="mr-1" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
        follow this problem&rsquo;s approved plan
      </label>
      <button type="button" disabled={busy || !decision} onClick={() => void keep()}
        className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-60">
        Keep as data
      </button>
      {said && <p role="status" className="basis-full text-xs text-slate-700">{said}</p>}
    </div>
  );
}

export default function RunOutputs({ runId, status, ir }: { runId: Id; status: string; ir?: Record<string, unknown> }) {
  const answered = status === "optimal" || status === "feasible";
  // Any map data under the answer (roads, zones, incident heat), and the flows drawn along its
  // lines rather than straight (benchmark, October 2026).
  const { domainId } = useDomain();
  const datasets = useDatasets(answered ? domainId : null);
  const [overlay, setOverlay] = useState<number | null>(null);
  const [alongLayer, setAlongLayer] = useState("");
  const overlaid = useQuery({
    queryKey: ["answer-overlay", overlay],
    queryFn: async () => ({ dataset: await getDataset(overlay as number), features: await getFeatures(overlay as number) }),
    enabled: overlay !== null,
  });
  const lineLayers = (overlaid.data?.dataset.layers ?? []).filter((l) => (l.kinds?.line ?? 0) > 0);
  const along = overlay !== null && alongLayer && lineLayers.some((l) => l.name === alongLayer)
    ? `?along_dataset=${overlay}&along_layer=${encodeURIComponent(alongLayer)}` : "";
  const map = useQuery({
    queryKey: ["answer-map", runId, along],
    queryFn: () => apiFetch<AnswerMap>(`/api/v1/runs/${runId}/answer-map${along}`),
    enabled: answered,
    retry: false,
    placeholderData: (previous) => previous,
  });
  const [failed, setFailed] = useState<string | null>(null);
  const [colourBy, setColourBy] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);
  const basemaps = useBasemaps();
  if (!answered) return null;
  const decisions = Object.entries(((ir?.variables ?? {}) as Record<string, { index?: string[]; domain?: string }>))
    .filter(([, spec]) => spec.domain !== "interval" && (spec.index?.length ?? 0) > 0);
  // Only a whole answer map is drawn: a server from before it existed answers something else, or nothing.
  const usable = map.data && !map.data.none && Array.isArray(map.data.features) && Array.isArray(map.data.layers)
    && map.data.features.length > 0;
  const plain = usable && map.data ? marksOf(map.data) : null;
  const fields = usable && map.data ? areaFields(map.data) : [];
  const coloured = plain && map.data && colourBy ? colourAreas(map.data, plain.marks, colourBy) : null;
  const answerDrawn = plain && coloured ? { ...plain, marks: coloured.marks } : plain;
  const under: GeoMark[] = (overlaid.data?.features.features ?? []).filter((f) => f.properties.kind !== "text").map((f, i) => ({
    id: `overlay-${i}`, geometry: f.geometry as GeoGeometry, colour: f.properties.color ?? "#94a3b8",
    size: f.geometry.type === "Point" ? 2 : 1.5, fill: 0.08, title: `${f.properties.layer}`, layer: `under: ${f.properties.layer}`,
  }));
  const drawn = answerDrawn && under.length
    ? { marks: [...under, ...answerDrawn.marks],
        legend: [...(answerDrawn.legend ?? []), ...[...new Set(under.map((m) => m.layer))].map((layer) => ({
          layer, colour: under.find((m) => m.layer === layer)?.colour ?? "#94a3b8",
          text: `${layer.slice("under: ".length)} (${overlaid.data?.dataset.name ?? "map data"}, under the answer)` }))] }
    : answerDrawn;
  const report = () => {
    setFailed(null);
    // The report is an HTML page the browser prints or saves as PDF; fetched with the session, opened as a page.
    const opened = window.open("", "_blank");
    // The background the person has under the map goes onto the paper too (user test: a printed map on white).
    let background: string | null = basemaps.chosen?.id ?? null;
    try {
      background = localStorage.getItem(BASEMAP_STORAGE_KEY) ?? background;
    } catch {
      /* storage unavailable: the default background */
    }
    const under = background ? `&basemap=${encodeURIComponent(background)}` : "";
    apiDownload(`/api/v1/runs/${runId}/export?format=html&print=true${under}`)
      .then(({ blob }) => {
        const url = URL.createObjectURL(blob);
        if (opened) opened.location.href = url;
        else window.location.assign(url);
      })
      .catch((e) => { opened?.close(); setFailed(formatApiError(e)); });
  };
  // The report as a file (WeasyPrint on the server), with the background the person has under the map.
  const pdf = () => {
    setFailed(null);
    setPdfBusy(true);
    let background: string | null = basemaps.chosen?.id ?? null;
    try {
      background = localStorage.getItem(BASEMAP_STORAGE_KEY) ?? background;
    } catch {
      /* storage unavailable: the default background */
    }
    const under = background ? `&basemap=${encodeURIComponent(background)}` : "";
    downloadFrom(`/api/v1/runs/${runId}/export?format=pdf${under}`)
      .catch((e) => setFailed(formatApiError(e)))
      .finally(() => setPdfBusy(false));
  };
  const download = (format: "xlsx" | "csv" | "geojson") => {
    setFailed(null);
    downloadFrom(`/api/v1/runs/${runId}/export?format=${format}`).catch((e) => setFailed(formatApiError(e)));
  };
  return (
    <section aria-label="Answer outputs" className="mb-4 space-y-3 rounded-md border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold text-slate-900">Take the answer out</span>
        <button type="button" onClick={() => download("xlsx")} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50">Excel</button>
        <button type="button" onClick={() => download("csv")} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50">CSV</button>
        <button type="button" onClick={() => pdf()} disabled={pdfBusy} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50 disabled:opacity-60">
          {pdfBusy ? "Making the PDF…" : "PDF report"}
        </button>
        <button type="button" onClick={report} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50" title="Opens the same report with the print dialog.">Print</button>
        {drawn && <button type="button" onClick={() => download("geojson")} className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-50">GeoJSON (map)</button>}
        {failed && <span role="alert" className="text-xs text-red-700">{failed}</span>}
      </div>
      {drawn && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">On the map</h3>
          <GeoMap marks={drawn.marks} legend={drawn.legend} ramp={coloured?.ramp ?? undefined}
            controls={<>
              {fields.length > 0 && (
              <label className="flex items-center gap-1">Colour areas by
                <select aria-label="Colour areas by" className="rounded border border-slate-300 px-1 py-0.5 text-xs" value={colourBy}
                  onChange={(e) => setColourBy(e.target.value)}>
                  <option value="">their layer</option>
                  {fields.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </label>
              )}
              {(datasets.data?.items ?? []).length > 0 && (
                <label className="flex items-center gap-1">Show under it
                  <select aria-label="Show under the answer" className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                    value={overlay ?? ""} onChange={(e) => { setOverlay(e.target.value ? Number(e.target.value) : null); setAlongLayer(""); }}>
                    <option value="">nothing</option>
                    {(datasets.data?.items ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </label>
              )}
              {lineLayers.length > 0 && (
                <label className="flex items-center gap-1">Flows along
                  <select aria-label="Draw flows along" className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                    value={alongLayer} onChange={(e) => setAlongLayer(e.target.value)}>
                    <option value="">straight lines</option>
                    {lineLayers.map((l) => <option key={l.id} value={l.name}>{l.name}</option>)}
                  </select>
                </label>
              )}
            </>}
            caption={`${(map.data?.layers ?? []).map((l) => l.title).join(" · ")}${map.data?.truncated ? " · the first 20,000 shown" : ""}${
              coloured?.ramp ? ` · areas filled by ${colourBy}; a chosen area deeper` : ""}`} />
        </div>
      )}
      <KeepAsData runId={runId} decisions={decisions} />
    </section>
  );
}
