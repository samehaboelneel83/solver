/**
 * Import a spatial file as map data (DXF, GeoJSON, KML/KMZ, GPX, Shapefile, GeoPackage, CSV -> GIS):
 *
 * 1. the file: read on the server into layers of points, lines, polygons and text;
 * 2. the layers to keep, with their CAD colours and what each holds;
 * 3. where it is: a coordinate system chosen by where the drawing lands,
 *    previewed over imagery before anything is stored (`PlacementPicker`);
 * 4. a name; then the features are stored and opened on the map.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, FileUp, MapPinned } from "lucide-react";
import { formatApiError } from "../api/errors";
import { importDataset, previewUpload, uploadCandidates, uploadDrawing, type GisPreview, type GisUpload, type SiteWhere } from "../api/gis";
import SiteMap, { fitRings, useSiteBasemap, type MapView } from "../components/map/SiteMap";
import PlacementPicker, { SiteWherePicker, storedWhere, type PickerState } from "../components/map/PlacementPicker";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { toLonLat } from "../lib/campGeo";
import { draw, extentOf, prepare } from "../lib/gisDraw";
import type { Pt } from "../api/camps";

/** The files Map data reads (backend `app/gis/formats.py`). */
export const SPATIAL_FILES = ".dxf,.geojson,.json,.kml,.kmz,.gpx,.zip,.gpkg,.csv";

const KIND_WORDS: Record<string, string> = { point: "points", line: "lines", polygon: "areas", text: "texts" };

export default function MapImport() {
  useDocumentTitle("Import map data");
  const { domainId } = useDomain();
  const navigate = useNavigate();
  const { can } = useCapabilities();
  const [upload, setUpload] = useState<GisUpload | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Set<string>>(new Set());
  const [pick, setPick] = useState<PickerState>({ placement: null, units: null });
  const [where, setWhere] = useState<SiteWhere>(storedWhere);
  const [preview, setPreview] = useState<GisPreview | null>(null);
  const [name, setName] = useState("");
  const [view, setView] = useState<MapView>({ cx: 0, cy: 0, mpp: 1 });
  const size = useRef<[number, number]>([800, 520]);
  const basemap = useSiteBasemap();
  const file = useRef<HTMLInputElement>(null);

  const read = async (f: File | undefined) => {
    if (!f || domainId === null) return;
    setBusy(`Reading ${f.name}…`);
    setError(null);
    try {
      const got = await uploadDrawing(f, domainId, where.point ? null : where.region);
      if (where.point) got.candidates = (await uploadCandidates(got.upload_id, where)).candidates;
      setUpload(got);
      // AutoCAD's Defpoints never prints: left out unless chosen.
      setLayers(new Set(got.summary.layers.filter((l) => l.features > 0 && l.on && !l.frozen && l.name.toLowerCase() !== "defpoints").map((l) => l.name)));
      setName(f.name.replace(/\.[a-z0-9]+$/i, "").replace(/[_]+/g, " "));
      // Chosen for the person only when the evidence is good: a world-wide system that merely fits is not.
      const sure = got.candidates.find((c) => c.sure);
      setPick({ placement: sure?.placement ?? null, units: null });
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
      if (file.current) file.current.value = "";
    }
  };

  // The preview follows the placement, the units and the layers, a moment after they settle.
  const layerList = useMemo(() => [...layers].sort(), [layers]);
  useEffect(() => {
    if (!upload || !pick.placement) { setPreview(null); return; }
    const timer = window.setTimeout(() => {
      previewUpload(upload.upload_id, { placement: pick.placement!, units: pick.units, layers: layerList })
        .then((got) => { setPreview(got); setError(null); })
        .catch((e) => { setPreview(null); setError(formatApiError(e)); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [upload, pick, layerList]);

  const origin: Pt = useMemo(() => {
    const b = preview?.bbox;
    return b ? [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] : [31.2357, 30.0444];
  }, [preview?.bbox]);
  const items = useMemo(() => prepare(preview?.features.features ?? [], origin), [preview, origin]);

  // Fit the preview whenever it moves somewhere new.
  const fittedFor = useRef<string>("");
  useEffect(() => {
    const key = origin.map((v) => v.toFixed(4)).join(",");
    if (!items.length || fittedFor.current === key) return;
    fittedFor.current = key;
    const e = extentOf(items);
    if (e) {
      const v = fitRings([[[e[0], e[1]], [e[2], e[3]]]], size.current[0], size.current[1]);
      if (v) setView(v);
    }
  }, [items, origin]);

  const colours = useMemo(() => Object.fromEntries((upload?.summary.layers ?? []).map((l) => [l.name, l.color])), [upload]);
  const canvas = useCallback((ctx: CanvasRenderingContext2D, at: (p: Pt) => [number, number], mpp: number) => {
    const half = [size.current[0] / 2 * mpp, size.current[1] / 2 * mpp];
    draw(ctx, items, at, mpp, {
      visible: () => true, colour: (p) => String(p.feature.properties.color ?? colours[p.layer] ?? "#1f2937"),
      view: [view.cx - half[0], view.cy - half[1], view.cx + half[0], view.cy + half[1]],
    });
  }, [items, colours, view]);

  const save = async () => {
    if (!upload || !pick.placement || domainId === null) return;
    setBusy("Importing…");
    setError(null);
    try {
      const made = await importDataset({ upload_id: upload.upload_id, domain_id: domainId, name: name.trim() || upload.filename,
        placement: pick.placement, units: pick.units, layers: layerList });
      navigate(`/domains/${domainId}/map-data/${made.id}`);
    } catch (e) {
      setError(formatApiError(e));
      setBusy(null);
    }
  };

  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;
  if (!can("domain.edit")) return <p className="text-sm text-slate-600">Importing map data needs permission to edit this domain.</p>;

  const s = upload?.summary;
  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-2">
        <Link to={`/domains/${domainId}/map-data`} className="text-sm text-blue-700 hover:underline">Map data</Link>
        <span className="text-slate-400">/</span>
        <h1 className="text-lg font-semibold text-slate-900">Import map data</h1>
      </header>

      {!upload && (
        <section className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void read(e.dataTransfer.files[0]); }}>
          <FileUp className="mx-auto h-8 w-8 text-slate-400" aria-hidden />
          <p className="mt-2 text-sm text-slate-700">Drop a CAD drawing or GIS file here, or</p>
          <button type="button" disabled={!!busy} onClick={() => file.current?.click()}
            className="mt-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            {busy ?? "Choose a file"}
          </button>
          <input ref={file} type="file" accept={SPATIAL_FILES} className="hidden" aria-label="Map data file" onChange={(e) => void read(e.target.files?.[0])} />
          <ul className="mx-auto mt-3 max-w-xl space-y-0.5 text-left text-xs text-slate-500">
            <li><strong>CAD drawing</strong> (.dxf): every layer, with points, lines, closed shapes, hatches, circles, text and
              blocks. A DWG must be saved as DXF from your CAD program first.</li>
            <li><strong>GeoJSON</strong> (.geojson, .json), <strong>KML / KMZ</strong> (Google Earth), <strong>GPX</strong> (GPS):
              in longitude and latitude, so they land on the map by themselves.</li>
            <li><strong>Shapefile</strong>: a .zip of its .shp, .shx, .dbf and .prj. <strong>GeoPackage</strong> (.gpkg): each
              table a layer. Both bring their coordinate system and attributes.</li>
            <li><strong>CSV</strong>: a WKT column (wkt or geometry), or lon/lat or x/y columns; a layer column makes layers.</li>
          </ul>
          {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
        </section>
      )}

      {upload && s && (
        <div className="grid gap-4 xl:grid-cols-[340px_1fr_340px]">
          <section className="rounded-lg border border-slate-200 bg-white p-3" aria-label="Layers">
            <h2 className="text-sm font-semibold text-slate-900">1. Layers</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {upload.filename} · {/^AC\d/.test(s.version) ? `DXF ${s.version}` : s.version} · {s.features.toLocaleString()} features ·
              {" "}{Object.entries(s.kinds).map(([k, n]) => `${n.toLocaleString()} ${KIND_WORDS[k] ?? k}`).join(", ")}
            </p>
            <div className="mt-2 flex gap-2 text-xs">
              <button type="button" className="text-blue-700 hover:underline" onClick={() => setLayers(new Set(s.layers.map((l) => l.name)))}>All</button>
              <button type="button" className="text-blue-700 hover:underline" onClick={() => setLayers(new Set())}>None</button>
            </div>
            <ul className="mt-1 max-h-[440px] divide-y divide-slate-100 overflow-y-auto rounded border border-slate-200">
              {s.layers.map((l) => (
                <li key={l.name}>
                  <label className="flex cursor-pointer items-start gap-2 px-2 py-1.5 text-xs hover:bg-slate-50">
                    <input type="checkbox" checked={layers.has(l.name)} className="mt-0.5"
                      onChange={(e) => { const next = new Set(layers); if (e.target.checked) next.add(l.name); else next.delete(l.name); setLayers(next); }} />
                    <span className="mt-0.5 inline-block h-3 w-3 shrink-0 rounded-sm border border-slate-300" style={{ background: l.color }} />
                    <span className="min-w-0 flex-1">
                      <span className="font-medium text-slate-900">{l.name}</span>
                      {(!l.on || l.frozen) && <span className="ml-1 text-slate-400">({!l.on ? "off" : "frozen"} in the drawing)</span>}
                      <span className="block text-slate-500">
                        {Object.entries(l.kinds).map(([k, n]) => `${n} ${KIND_WORDS[k] ?? k}`).join(", ") || "empty"}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            {(s.notes.length > 0 || Object.keys(s.skipped).length > 0) && (
              <ul className="mt-2 space-y-0.5 text-xs text-amber-800">
                {s.notes.map((n) => <li key={n}>{n}</li>)}
                {Object.entries(s.skipped).map(([k, n]) => <li key={k}>{n} {k} not shown on a map (no 2D geometry)</li>)}
              </ul>
            )}
          </section>

          <section className="min-w-0" aria-label="Preview">
            <SiteMap origin={origin} view={view} onView={setView} basemap={basemap.chosen} height={560}
              onSize={(w, h) => { size.current = [w, h]; }} canvas={canvas} label="Where the drawing lands"
              onClick={(p) => {
                // Local coordinates: a click puts the drawing point here.
                if (pick.placement?.kind !== "local") return;
                const here = toLonLat(p, origin);
                setPick({ ...pick, placement: { ...pick.placement, lonlat: [Number(here[0].toFixed(7)), Number(here[1].toFixed(7))] } });
              }}
              overlay={
                <div className="pointer-events-none absolute left-2 top-2 max-w-[75%] space-y-1">
                  {preview ? (
                    <p className="rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow-sm">
                      {preview.total.toLocaleString()} features{preview.sampled ? ` (a sample of ${preview.features.features.length.toLocaleString()} shown)` : ""}
                      {preview.bbox ? ` around ${((preview.bbox[1] + preview.bbox[3]) / 2).toFixed(5)}, ${((preview.bbox[0] + preview.bbox[2]) / 2).toFixed(5)}` : ""}
                    </p>
                  ) : (
                    <p className="rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow-sm">Choose where the drawing is to see it on the map.</p>
                  )}
                  {preview?.warnings.map((w) => (
                    <p key={w} role="alert" className="flex items-center gap-1 rounded bg-amber-50/95 px-2 py-1 text-xs text-amber-900 shadow-sm">
                      <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {w}
                    </p>
                  ))}
                </div>
              } />
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-600">
              Background
              <select value={basemap.chosen?.id ?? "none"} onChange={(e) => basemap.choose(e.target.value)} aria-label="Background"
                className="rounded border border-slate-300 bg-white px-1 py-0.5">
                {basemap.options.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                <option value="none">No background</option>
              </select>
              <span className="text-slate-400">Check the drawing sits where it should on the imagery before importing.</span>
            </div>
            {preview && <AttributeSample features={preview.features.features} />}
          </section>

          <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3" aria-label="Where it is">
            <h2 className="text-sm font-semibold text-slate-900">2. Where is it?</h2>
            <p className="text-xs text-slate-500">
              The drawing's numbers run from {s.extent ? `${s.extent[0].toFixed(1)}, ${s.extent[1].toFixed(1)} to ${s.extent[2].toFixed(1)}, ${s.extent[3].toFixed(1)}` : "—"}.
              {typeof s.geodata?.epsg === "number"
                ? ` The file names its coordinate system (EPSG:${s.geodata.epsg}); check it lands in the right place.`
                : " A DXF or a CSV rarely says which coordinate system they are in; choose the one that puts it in the right place."}
            </p>
            <SiteWherePicker value={where} onChange={(w) => {
              setWhere(w);
              void uploadCandidates(upload.upload_id, w).then((got) => {
                setUpload({ ...upload, candidates: got.candidates });
                const sure = got.candidates.find((c) => c.sure);
                // A new place answers afresh: the sure choice there, or none -- never a zone left from before.
                setPick((current) => (current.placement?.kind === "local" ? current : { ...current, placement: sure?.placement ?? null }));
              }).catch((e) => setError(formatApiError(e)));
            }} />
            <PlacementPicker value={pick} onChange={setPick} candidates={upload.candidates} zones={upload.utm_zones}
              extent={s.extent} drawingUnits={s.units_name} />
            <h2 className="pt-2 text-sm font-semibold text-slate-900">3. Name and import</h2>
            <label className="block text-xs text-slate-600">
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
                className="mt-0.5 w-full rounded border border-slate-300 px-1.5 py-1 text-sm" />
            </label>
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <button type="button" onClick={() => void save()}
              disabled={!!busy || !pick.placement || !preview || !preview.bbox || layers.size === 0}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              <MapPinned className="h-4 w-4" aria-hidden /> {busy ?? `Import ${layers.size} layer${layers.size === 1 ? "" : "s"}`}
            </button>
            <button type="button" className="w-full text-xs text-slate-600 underline" onClick={() => { setUpload(null); setPreview(null); }}>
              Choose another file
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

/** Properties the importer adds itself, not the file's own attributes. */
const OWN = new Set(["layer", "kind", "color", "colour", "text", "block", "block_path", "handle", "linetype", "lineweight", "entity", "part"]);

/** The first features' attributes, so what the file carries is seen before importing (user trial). */
export function AttributeSample({ features }: { features: { properties?: Record<string, unknown> | null }[] }) {
  const rows = features.slice(0, 5).map((f) => f.properties ?? {});
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((c) => !OWN.has(c));
  if (!columns.length) return null;
  return (
    <div className="mt-2 max-h-48 overflow-auto rounded border border-slate-200 bg-white">
      <table className="text-left text-xs" aria-label="What each feature carries">
        <caption className="px-2 py-1 text-left text-slate-600">What the features carry (first {rows.length})</caption>
        <thead>
          <tr className="bg-slate-50 text-slate-600">
            {columns.map((c) => <th key={c} scope="col" className="whitespace-nowrap px-2 py-1 font-mono font-medium">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-100">
              {columns.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1">{r[c] == null ? "" : typeof r[c] === "object" ? "…" : String(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
