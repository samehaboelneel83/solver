/**
 * One imported drawing on the map: its layers over imagery in their CAD
 * colours, text at its height and angle, block references as points.
 * Click a feature for its properties (entity, layer, block, attributes,
 * text); search text and attributes; turn layers on and off and recolour
 * them; place the drawing again with another coordinate system; export it as
 * GeoJSON or CSV (WKT).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Crosshair, Download, Maximize2, Search, Trash2 } from "lucide-react";
import { formatApiError } from "../api/errors";
import {
  datasetCandidates, deleteDataset, editLayer, placeDataset, useDataset, useFeatures, type GisDataset, type SiteWhere,
} from "../api/gis";
import { downloadFrom } from "../api/download";
import type { Pt } from "../lib/geo";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import LoadFailure from "../components/LoadFailure";
import Skeleton from "../components/Skeleton";
import SiteMap, { fitRings, useSiteBasemap, type At, type MapView as View } from "../components/map/SiteMap";
import PlacementPicker, { SiteWherePicker, storedWhere, type PickerState } from "../components/map/PlacementPicker";
import LayersToRecords from "../components/map/LayersToRecords";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { draw, extentOf, hit, prepare, type Prepared } from "../lib/gisDraw";
import { CopyMapData } from "../components/CopyMapData";

const KIND_WORDS: Record<string, string> = { point: "points", line: "lines", polygon: "areas", text: "texts" };
const HIDDEN_PROPS = new Set(["layer_id"]);

function value(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${String(x)}`).join(", ");
  return String(v);
}

export default function MapView() {
  const { datasetId } = useParams();
  const id = Number(datasetId);
  const ds = useDataset(Number.isInteger(id) && id > 0 ? id : null);
  const { domainId } = useDomain();
  useDocumentTitle(ds.data?.name ?? "Map data");
  if (ds.isLoading) return <Skeleton rows={8} />;
  if (ds.isError || !ds.data)
    return <LoadFailure subject="This map data" error={ds.error} retry={() => void ds.refetch()}
      back={domainId ? { label: "All map data", to: `/domains/${domainId}/map-data` } : undefined} />;
  return <Viewer key={ds.data.id} dataset={ds.data} />;
}

function Viewer({ dataset }: { dataset: GisDataset }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const feats = useFeatures(dataset.id, dataset.updated_at);
  const basemap = useSiteBasemap();
  const origin: Pt = useMemo(() => {
    const b = dataset.bbox;
    return b ? [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] : [0, 0];
  }, [dataset.bbox]);
  const items = useMemo(() => prepare(feats.data?.features ?? [], origin), [feats.data, origin]);
  const [view, setView] = useState<View>({ cx: 0, cy: 0, mpp: 1 });
  const size = useRef<[number, number]>([900, 600]);
  const [visible, setVisible] = useState<Record<string, boolean>>(() => Object.fromEntries(dataset.layers.map((l) => [l.name, l.visible])));
  const [colours, setColours] = useState<Record<string, string>>(() => Object.fromEntries(dataset.layers.map((l) => [l.name, l.color])));
  const [byLayer, setByLayer] = useState(false);
  const [labels, setLabels] = useState(true);
  const [selected, setSelected] = useState<Prepared | null>(null);
  const [tab, setTab] = useState<"layers" | "feature" | "records" | "details">("layers");
  const [query, setQuery] = useState("");
  const [placing, setPlacing] = useState(false);
  const [pick, setPick] = useState<PickerState>({ placement: dataset.placement, units: dataset.placement.units ?? null });
  const [message, setMessage] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [where, setWhere] = useState<SiteWhere>(storedWhere);
  const candidates = useQuery({ queryKey: ["gis", "candidates", dataset.id, where], queryFn: () => datasetCandidates(dataset.id, where), enabled: placing });

  const fitTo = useCallback((list: Prepared[]) => {
    const e = extentOf(list);
    if (!e) return;
    const v = fitRings([[[e[0], e[1]], [e[2], e[3]]]], size.current[0], size.current[1]);
    if (v) setView({ ...v, mpp: Math.max(v.mpp, 0.02) });
  }, []);
  const fitted = useRef(false);
  useEffect(() => {
    if (!fitted.current && items.length) { fitted.current = true; fitTo(items); }
  }, [items, fitTo]);

  const isVisible = useCallback((layer: string) => visible[layer] !== false, [visible]);
  const canvas = useCallback((ctx: CanvasRenderingContext2D, at: At, mpp: number) => {
    const half = [size.current[0] / 2 * mpp, size.current[1] / 2 * mpp];
    draw(ctx, items, at, mpp, {
      visible: isVisible, labels, selected: selected?.key ?? null,
      colour: (p) => (byLayer ? colours[p.layer] : String(p.feature.properties.color ?? colours[p.layer])) ?? "#1f2937",
      view: [view.cx - half[0], view.cy - half[1], view.cx + half[0], view.cy + half[1]],
    });
  }, [items, isVisible, labels, selected, byLayer, colours, view]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return items.filter((p) => {
      const props = p.feature.properties;
      return [props.text, props.block, value(props.attributes), props.handle].some((v) => v && String(v).toLowerCase().includes(q));
    }).slice(0, 50);
  }, [items, query]);

  const toggle = async (layer: GisDataset["layers"][number], on: boolean) => {
    setVisible({ ...visible, [layer.name]: on });
    if (canEdit) await editLayer(layer.id, { visible: on }).catch(() => undefined);
  };
  const recolour = async (layer: GisDataset["layers"][number], colour: string) => {
    setColours({ ...colours, [layer.name]: colour });
    if (canEdit) await editLayer(layer.id, { color: colour }).catch(() => undefined);
  };

  const applyPlacement = async () => {
    if (!pick.placement) return;
    setMessage("Placing again…");
    try {
      await placeDataset(dataset.id, pick.placement, pick.units);
      fitted.current = false;
      setPlacing(false);
      setMessage(null);
      await client.invalidateQueries({ queryKey: ["gis"] });
    } catch (e) {
      setMessage(formatApiError(e));
    }
  };

  const props: Record<string, unknown> = selected?.feature.properties ?? {};
  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[560px] flex-col gap-2">
      <header className="flex flex-wrap items-center gap-2">
        <Link to={`/domains/${dataset.domain_id}/map-data`} className="text-sm text-blue-700 hover:underline">Map data</Link>
        <span className="text-slate-400">/</span>
        <h1 className="text-lg font-semibold text-slate-900">{dataset.name}</h1>
        <span className="text-xs text-slate-500">
          {(dataset.stats.features ?? 0).toLocaleString("en-US")} features · {dataset.layers.length} layers ·{" "}
          {dataset.placement.kind === "epsg" ? dataset.placement.name ?? `EPSG:${dataset.placement.code}` : "local coordinates"}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          {can("domain.edit") && <CopyMapData datasetId={dataset.id} fromDomain={dataset.domain_id} name={dataset.name} />}
          <select value={basemap.chosen?.id ?? "none"} onChange={(e) => basemap.choose(e.target.value)} aria-label="Background"
            className="rounded border border-slate-300 bg-white px-1 py-1">
            {basemap.options.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            <option value="none">No background</option>
          </select>
          <button type="button" onClick={() => fitTo(items.filter((p) => isVisible(p.layer)))}
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50">
            <Maximize2 className="h-3.5 w-3.5" aria-hidden /> Fit
          </button>
          <Link to={`/domains/${dataset.domain_id}/map-data?records=1`}
            className="inline-flex items-center gap-1 rounded border border-blue-600 bg-white px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">
            Map to records
          </Link>
          {(["geojson", "csv"] as const).map((f) => (
            <button key={f} type="button" onClick={() => void downloadFrom(`/api/v1/gis/datasets/${dataset.id}/export?format=${f}`)}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50">
              <Download className="h-3.5 w-3.5" aria-hidden /> {f === "geojson" ? "GeoJSON" : "CSV (WKT)"}
            </button>
          ))}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 gap-3">
        <div className="relative min-w-0 flex-1">
          <SiteMap origin={origin} view={view} onView={setView} basemap={basemap.chosen} height="100%" canvas={canvas}
            onSize={(w, h) => { size.current = [w, h]; }} label={`Map of ${dataset.name}`}
            onClick={(p) => {
              const found = hit(items, p, view.mpp, isVisible);
              setSelected(found);
              if (found) setTab("feature");
            }}
            overlay={feats.isLoading ? (
              <p className="absolute left-2 top-2 rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow-sm">Loading features…</p>
            ) : feats.data?.truncated ? (
              <p className="absolute left-2 top-2 rounded bg-amber-50/95 px-2 py-1 text-xs text-amber-900 shadow-sm">
                Only the first {feats.data.features.length.toLocaleString("en-US")} features are shown.
              </p>
            ) : null} />
        </div>
        <aside className="flex w-[360px] shrink-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="Map data details">
          <div className="flex border-b border-slate-200 text-xs font-medium" role="tablist">
            {([["layers", "Layers"], ["feature", "Feature"], ["records", "Use in models"], ["details", "Source & location"]] as const).map(([k, text]) => (
              <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`flex-1 px-2 py-2 ${tab === k ? "border-b-2 border-blue-600 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>{text}</button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm">
            {tab === "layers" && (
              <div className="space-y-3">
                <label className="flex items-center gap-1.5 rounded border border-slate-200 px-2 py-1 text-xs">
                  <Search className="h-3.5 w-3.5 text-slate-400" aria-hidden />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find text, blocks, attributes…"
                    className="w-full outline-none" aria-label="Find in the drawing" />
                </label>
                {matches.length > 0 && (
                  <ul className="max-h-44 overflow-y-auto rounded border border-slate-200 text-xs">
                    {matches.map((m) => (
                      <li key={m.key}>
                        <button type="button" className="flex w-full items-center gap-1.5 px-2 py-1 text-left hover:bg-slate-50"
                          onClick={() => { setSelected(m); setTab("feature"); setView({ cx: (m.box[0] + m.box[2]) / 2, cy: (m.box[1] + m.box[3]) / 2, mpp: Math.min(view.mpp, 0.1) }); }}>
                          <Crosshair className="h-3 w-3 text-slate-400" aria-hidden />
                          {String(m.feature.properties.text ?? m.feature.properties.block ?? m.kind)} <span className="text-slate-400">· {m.layer}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex flex-wrap gap-3 text-xs text-slate-700">
                  <label className="inline-flex items-center gap-1"><input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} /> Text</label>
                  <label className="inline-flex items-center gap-1"><input type="checkbox" checked={byLayer} onChange={(e) => setByLayer(e.target.checked)} /> One colour per layer</label>
                  <button type="button" className="text-blue-700 hover:underline" onClick={() => setVisible(Object.fromEntries(dataset.layers.map((l) => [l.name, true])))}>All on</button>
                  <button type="button" className="text-blue-700 hover:underline" onClick={() => setVisible(Object.fromEntries(dataset.layers.map((l) => [l.name, false])))}>All off</button>
                </div>
                <ul className="divide-y divide-slate-100 rounded border border-slate-200" aria-label="Layers">
                  {dataset.layers.map((l) => (
                    <li key={l.id} className="flex items-center gap-2 px-2 py-1.5 text-xs">
                      <input type="checkbox" checked={isVisible(l.name)} onChange={(e) => void toggle(l, e.target.checked)} aria-label={`Show ${l.name}`} />
                      <input type="color" value={colours[l.name] ?? l.color} onChange={(e) => void recolour(l, e.target.value)}
                        className="h-5 w-6 cursor-pointer rounded border border-slate-300 p-0" aria-label={`Colour of ${l.name}`} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-slate-900">{l.name}</span>
                        <span className="text-slate-500">{Object.entries(l.kinds).map(([k, n]) => `${n} ${KIND_WORDS[k] ?? k}`).join(", ")}</span>
                      </span>
                      <button type="button" title={`Zoom to ${l.name}`} aria-label={`Zoom to ${l.name}`}
                        onClick={() => fitTo(items.filter((p) => p.layer === l.name))} className="rounded p-1 text-slate-500 hover:bg-slate-100">
                        <Maximize2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {tab === "feature" && (
              selected ? (
                <section aria-label="Selected feature">
                  <h2 className="text-sm font-semibold text-slate-900">
                    {String(props.text ?? props.block ?? `${selected.kind} ${selected.feature.id ?? ""}`)}
                  </h2>
                  <p className="text-xs text-slate-500">{selected.kind} on layer {selected.layer}</p>
                  <table className="mt-2 w-full text-xs">
                    <tbody>
                      {Object.entries(props).filter(([k]) => !HIDDEN_PROPS.has(k)).map(([k, v]) => (
                        <tr key={k} className="border-t border-slate-100 align-top">
                          <th className="w-28 py-1 pr-2 text-left font-medium text-slate-600">{k}</th>
                          <td className="break-all py-1 text-slate-900">
                            {k === "color" ? <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm" style={{ background: String(v) }} />{String(v)}</span> : value(v)}
                          </td>
                        </tr>
                      ))}
                      <tr className="border-t border-slate-100">
                        <th className="py-1 pr-2 text-left font-medium text-slate-600">geometry</th>
                        <td className="py-1 text-slate-900">{selected.feature.geometry.type}
                          {selected.feature.geometry.type === "Point" ? ` ${(selected.feature.geometry.coordinates as number[]).map((c) => c.toFixed(7)).join(", ")}` : ""}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </section>
              ) : <p className="text-xs text-slate-500">Click a feature on the map to see what the drawing says about it.</p>
            )}
            {tab === "records" && <LayersToRecords dataset={dataset} canEdit={canEdit} />}
            {tab === "details" && (
              <div className="space-y-3 text-xs">
                <dl className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1">
                  <dt className="text-slate-500">File</dt><dd>{dataset.source.filename} ({/\.dxf$/i.test(dataset.source.filename ?? "") ? `DXF ${dataset.source.version ?? ""}`.trim() : dataset.source.version ?? "map file"})</dd>
                  <dt className="text-slate-500">Drawing units</dt><dd>{dataset.source.units ?? "not stated"}</dd>
                  <dt className="text-slate-500">Placed with</dt>
                  <dd>{dataset.placement.kind === "epsg" ? `${dataset.placement.name} (EPSG:${dataset.placement.code})`
                    : `local coordinates: (${dataset.placement.anchor.join(", ")}) at ${dataset.placement.lonlat[1]}, ${dataset.placement.lonlat[0]}, turned ${dataset.placement.rotation}°`}</dd>
                  <dt className="text-slate-500">Extent</dt><dd>{dataset.bbox?.map((v) => v.toFixed(5)).join(", ")}</dd>
                  <dt className="text-slate-500">Storage</dt><dd>{dataset.postgis ? "PostGIS (gis_feature.geom, SRID 4326)" : "GeoJSON in the database"}</dd>
                </dl>
                {dataset.notes.length > 0 && <ul className="list-disc pl-4 text-amber-800">{dataset.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
                {canEdit && (
                  <>
                    {!placing ? (
                      <button type="button" onClick={() => setPlacing(true)}
                        className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50">In the wrong place? Choose another coordinate system</button>
                    ) : (
                      <div className="space-y-2 rounded border border-blue-200 bg-blue-50/40 p-2">
                        <SiteWherePicker value={where} onChange={setWhere} />
                        <PlacementPicker value={pick} onChange={setPick} candidates={candidates.data?.candidates ?? []}
                          zones={candidates.data?.utm_zones ?? []} extent={candidates.data?.extent ?? null} drawingUnits={candidates.data?.units ?? null} />
                        <div className="flex gap-2">
                          <button type="button" onClick={() => void applyPlacement()} disabled={!pick.placement}
                            className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white disabled:opacity-50">Place again</button>
                          <button type="button" onClick={() => setPlacing(false)} className="underline">Cancel</button>
                        </div>
                      </div>
                    )}
                    {message && <p role="status" className="text-slate-700">{message}</p>}
                    {!confirmDelete ? (
                      <button type="button" onClick={() => setConfirmDelete(true)} className="inline-flex items-center gap-1 text-red-700 hover:underline">
                        <Trash2 className="h-3.5 w-3.5" aria-hidden /> Delete this map data
                      </button>
                    ) : (
                      <div className="rounded border border-amber-300 bg-amber-50 p-2 text-amber-900">
                        Delete {dataset.name} and its {(dataset.stats.features ?? 0).toLocaleString("en-US")} features?
                        <div className="mt-1 flex gap-2">
                          <button type="button" className="rounded bg-red-600 px-2 py-1 text-white"
                            onClick={() => void deleteDataset(dataset.id).then(() => { void client.invalidateQueries({ queryKey: ["gis"] }); navigate(`/domains/${dataset.domain_id}/map-data`); })}>
                            Delete
                          </button>
                          <button type="button" className="underline" onClick={() => setConfirmDelete(false)}>Keep it</button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
