import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import SiteMap, { fitRings, useSiteBasemap, type At, type MapView } from "../map/SiteMap";
import type { GeoGeometry } from "../map/GeoMap";
import { useToast } from "../ToastProvider";
import { formatApiError } from "../../api/errors";
import { getEntity, updateEntity, type Entity, type EntityType } from "../../api/v1";
import { useCapabilities } from "../../hooks/useCapability";
import { parseLatLon, toLocal, toLonLat } from "../../lib/geo";
import { asGeometry, describeShape, middleOf, positionsOf, shapeOf, type DrawMode, type LonLat } from "../../lib/geoShape";

const HEIGHT = 340;
const BUTTON = "rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50";

function svgPath(points: LonLat[], origin: LonLat, at: At, close: boolean): string {
  return (
    points.map((p, i) => {
      const [x, y] = at(toLocal(p, origin));
      return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ") + (close ? "Z" : "")
  );
}

function Shape({ g, origin, at, colour, faint }: { g: GeoGeometry; origin: LonLat; at: At; colour: string; faint?: boolean }) {
  if (g.type === "Point") {
    const [x, y] = at(toLocal(g.coordinates as LonLat, origin));
    return <circle cx={x} cy={y} r={faint ? 4 : 7} fill={colour} stroke="#fff" strokeWidth={1.5} opacity={faint ? 0.6 : 1} />;
  }
  const lines = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : null;
  if (lines) {
    return <path d={lines.map((l) => svgPath(l as LonLat[], origin, at, false)).join(" ")} fill="none" stroke={colour} strokeWidth={faint ? 1.5 : 3} opacity={faint ? 0.6 : 1} />;
  }
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  return (
    <path d={polys.flatMap((rings) => rings.map((r) => svgPath(r as LonLat[], origin, at, true))).join(" ")}
      fill={colour} fillOpacity={faint ? 0.08 : 0.25} stroke={colour} strokeWidth={faint ? 1 : 2} fillRule="evenodd" />
  );
}

/**
 * Where a record is, on a map you can pan and zoom: its shape, the shapes around it (its parent, the
 * records beside it) faintly, and tools to put it right -- click a point, draw a line or an area,
 * or type a latitude and longitude. Saved into the record's shape field, as the form would.
 */
export default function LocationEditor({
  entity,
  type,
  context = [],
}: {
  entity: Entity;
  type: EntityType;
  /** Shapes to show for orientation, not edited: the parent's area, the siblings' places. */
  context?: GeoGeometry[];
}) {
  const { can } = useCapabilities();
  const toast = useToast();
  const queryClient = useQueryClient();
  const fields = type.attributes.filter((a) => a.data_type === "geometry").map((a) => a.name);
  const [field, setField] = useState(fields[0]);
  const stored = asGeometry(entity.attrs?.[field]);
  const [mode, setMode] = useState<DrawMode | null>(null);
  const [draft, setDraft] = useState<LonLat[]>([]);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [origin, setOrigin] = useState<LonLat | null>(() => middleOf([...(stored ? [stored] : []), ...context]));
  // The surroundings load after the editor opens: centre on them when they come, if nothing else did.
  const around = middleOf([...(stored ? [stored] : []), ...context]);
  useEffect(() => {
    if (!origin && around) setOrigin(around);
  }, [origin, around?.[0], around?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  const basemap = useSiteBasemap();
  const [view, setView] = useState<MapView | null>(null);

  // The first view frames the record (or its surroundings) once the map's origin is known.
  const framed = useMemo(() => {
    if (!origin) return null;
    // The record and what is around it, and never less than 400 m across: a lone point is not a 1 m map.
    const points = [...(stored ? [stored] : []), ...context].flatMap(positionsOf).map((p) => toLocal(p, origin));
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const [cx, cy] = points.length ? [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] : [0, 0];
    const half = Math.max(200, ...xs.map((x) => Math.abs(x - cx)), ...ys.map((y) => Math.abs(y - cy)));
    return fitRings([[[cx - half, cy - half], [cx + half, cy + half]]], 520, HEIGHT) ?? { cx: 0, cy: 0, mpp: 2 };
  }, [origin, stored, context]);
  const shownView = view ?? framed;

  if (fields.length === 0) return <p className="text-sm text-slate-500">This kind of record has no shape field.</p>;

  async function save(geometry: GeoGeometry | null) {
    setBusy(true);
    try {
      const fresh = await getEntity(entity.id);
      const attrs = { ...fresh.attrs };
      if (geometry) attrs[field] = geometry;
      else delete attrs[field];
      await updateEntity(entity.id, { attrs, updated_at: fresh.updated_at });
      toast.success(geometry ? `${entity.key}: ${describeShape(geometry)}` : `${entity.key}: place cleared`);
      setMode(null);
      setDraft([]);
      await queryClient.invalidateQueries({ queryKey: ["v1"] });
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const result = mode ? shapeOf(mode, draft) : null;
  const editable = can("domain.edit");
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {fields.length > 1 && (
          <select aria-label="Shape field" className="rounded border border-slate-300 px-1 py-0.5 text-xs" value={field}
            onChange={(e) => { setField(e.target.value); setMode(null); setDraft([]); }}>
            {fields.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        )}
        <span className="text-slate-700">
          <span className="font-mono text-xs">{field}</span>: {describeShape(stored)}
        </span>
      </div>
      {editable && (
        <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Draw">
          {(["point", "line", "area"] as const).map((m) => (
            <button key={m} type="button" className={`${BUTTON} ${mode === m ? "border-blue-500 bg-blue-50" : ""}`} aria-pressed={mode === m}
              disabled={!origin} onClick={() => { setMode(m); setDraft([]); }}>
              {m === "point" ? "Place a point" : m === "line" ? "Draw a line" : "Draw an area"}
            </button>
          ))}
          {mode && draft.length > 0 && <button type="button" className={BUTTON} onClick={() => setDraft(draft.slice(0, -1))}>Undo last</button>}
          {mode && <button type="button" className={BUTTON} onClick={() => { setMode(null); setDraft([]); }}>Cancel</button>}
          {stored && !mode && <button type="button" className={BUTTON} disabled={busy} onClick={() => void save(null)}>Clear</button>}
        </div>
      )}
      {editable && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => {
          e.preventDefault();
          const p = parseLatLon(typed);
          if (!p) { toast.error("Write a latitude and a longitude, such as 30.0444, 31.2357"); return; }
          if (!origin) setOrigin(p as LonLat);
          setView(null);
          if (mode === "line" || mode === "area") setDraft([...draft, p as LonLat]);
          else { setMode("point"); setDraft([p as LonLat]); }
          setTyped("");
        }}>
          <label className="text-xs text-slate-600" htmlFor={`latlon-${entity.id}`}>Latitude, longitude</label>
          <input id={`latlon-${entity.id}`} className="w-48 rounded border border-slate-300 px-2 py-1 text-xs" placeholder="30.0444, 31.2357"
            value={typed} onChange={(e) => setTyped(e.target.value)} />
          <button type="submit" className={BUTTON}>{mode === "line" || mode === "area" ? "Add" : "Put it here"}</button>
        </form>
      )}
      {origin && shownView ? (
        <div className="overflow-hidden rounded border border-slate-200" data-testid="location-map">
          <SiteMap
            origin={origin}
            view={shownView}
            onView={setView}
            basemap={basemap.chosen}
            height={HEIGHT}
            cursor={mode ? "crosshair" : undefined}
            label={`Where ${entity.key} is`}
            onClick={(p) => {
              if (!mode) return;
              const lonlat = toLonLat(p, origin) as LonLat;
              setDraft(mode === "point" ? [lonlat] : [...draft, lonlat]);
            }}
          >
            {(at) => (
              <>
                {context.map((g, i) => <Shape key={`c${i}`} g={g} origin={origin} at={at} colour="#64748b" faint />)}
                {stored && !(result && "geometry" in result) && <Shape g={stored} origin={origin} at={at} colour="#2563eb" />}
                {result && "geometry" in result && <Shape g={result.geometry} origin={origin} at={at} colour="#ea580c" />}
                {mode && mode !== "point" && draft.map((p, i) => {
                  const [x, y] = at(toLocal(p, origin));
                  return <circle key={i} cx={x} cy={y} r={3.5} fill="#ea580c" stroke="#fff" />;
                })}
              </>
            )}
          </SiteMap>
        </div>
      ) : (
        <p className="rounded border border-dashed border-slate-300 p-4 text-sm text-slate-500">
          No place yet here or around it. Type a latitude and longitude above to start the map there.
        </p>
      )}
      {mode && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-600">
            {result && "problem" in result ? result.problem : `New: ${describeShape(result && "geometry" in result ? result.geometry : null)}`}
          </span>
          <button type="button" className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
            disabled={busy || !result || !("geometry" in result)}
            onClick={() => result && "geometry" in result && void save(result.geometry)}>
            Save the place
          </button>
        </div>
      )}
      <p className="text-xs text-slate-500">Drag to pan, wheel to zoom. Grey: what is around it.</p>
    </div>
  );
}
