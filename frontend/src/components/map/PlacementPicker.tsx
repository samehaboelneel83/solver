/**
 * Where a drawing is on the Earth: the coordinate system its numbers are in,
 * chosen by where it would land.
 *
 * Offered first: the likely systems (the drawing's own GEODATA, the domain's
 * usual one, degrees, the systems whose area of use it falls in), each with
 * the place it would land. Then every UTM zone with its place -- the numbers
 * alone cannot tell the zone -- any system in the EPSG registry by code or
 * name, or local engineering coordinates: a drawing point put at a longitude
 * and latitude (typed, or clicked on the map), turned and scaled.
 */
import { useState } from "react";
import { useCrsSearch, useRegions, type CrsCandidate, type GisPlacement, type LonLat, type SiteWhere } from "../../api/gis";
import { parseLatLon } from "../../lib/campGeo";

const FIELD = "w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-sm";
const UNITS: [string, number | null][] = [
  ["as the drawing says", null], ["millimetres", 0.001], ["centimetres", 0.01], ["metres", 1], ["kilometres", 1000],
  ["inches", 0.0254], ["feet", 0.3048], ["US survey feet", 1200 / 3937],
];

const at = (c: LonLat) => `${c[1].toFixed(4)}, ${c[0].toFixed(4)}`;
const WHERE_KEY = "solver_site_region";

/** Where the person last said their sites are: remembered in this browser. */
export function storedWhere(): SiteWhere {
  try {
    const raw = localStorage.getItem(WHERE_KEY);
    return raw ? (JSON.parse(raw) as SiteWhere) : { region: null, point: null };
  } catch {
    return { region: null, point: null };
  }
}
function storeWhere(where: SiteWhere) {
  try { localStorage.setItem(WHERE_KEY, JSON.stringify(where)); } catch { /* this page only */ }
}

/** "Roughly where is the site?": a country, or a position; the coordinate systems are searched there. */
export function SiteWherePicker({ value, onChange }: { value: SiteWhere; onChange: (w: SiteWhere) => void }) {
  const regions = useRegions();
  const [text, setText] = useState(value.point ? `${value.point[1]}, ${value.point[0]}` : "");
  const [byPoint, setByPoint] = useState(value.point !== null);
  const set = (w: SiteWhere) => { storeWhere(w); onChange(w); };
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-2">
      <label className="block text-xs font-semibold text-slate-700">
        Roughly where is the site?
        <select className={`mt-0.5 ${FIELD} font-normal`} aria-label="Country of the site"
          value={byPoint ? "@point" : value.region ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            setByPoint(v === "@point");
            if (v !== "@point") set({ region: v || null, point: null });
          }}>
          <option value="">not said</option>
          {(regions.data?.items ?? []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          <option value="@point">near a position…</option>
        </select>
      </label>
      {byPoint && (
        <span className="mt-1 flex gap-1">
          <input className={FIELD} value={text} onChange={(e) => setText(e.target.value)} placeholder="latitude, longitude e.g. 25.29, 51.53"
            aria-label="Position near the site" />
          <button type="button" className="rounded border border-slate-300 bg-white px-2 text-xs"
            onClick={() => { const q = parseLatLon(text); if (q) set({ region: null, point: q }); }}>Use</button>
        </span>
      )}
      <p className="mt-1 text-[11px] text-slate-500">
        The country's own grids and UTM zones are tried; only those that put the drawing there are offered.
      </p>
    </div>
  );
}

export type PickerState = { placement: GisPlacement | null; units: number | null };

export default function PlacementPicker({
  value, onChange, candidates, zones, extent, drawingUnits,
}: {
  value: PickerState;
  onChange: (v: PickerState) => void;
  candidates: CrsCandidate[];
  zones: { code: number; zone: string; centre: LonLat }[];
  extent: [number, number, number, number] | null;
  drawingUnits: string | null;
}) {
  const [query, setQuery] = useState("");
  const found = useCrsSearch(query);
  const [paste, setPaste] = useState("");
  const p = value.placement;
  const set = (placement: GisPlacement | null) => onChange({ ...value, placement });
  const code = p?.kind === "epsg" ? p.code : null;
  const local = p?.kind === "local" ? p : null;
  const localDefault: GisPlacement = {
    kind: "local", anchor: extent ? [extent[0], extent[1]] : [0, 0], lonlat: [31.2357, 30.0444], rotation: 0, scale: 1,
  };
  const zoneFor = zones.find((z) => z.code === code);

  return (
    <div className="space-y-3 text-sm">
      <label className="block text-xs text-slate-600">
        One drawing unit is
        <select className={`mt-0.5 ${FIELD}`} value={value.units ?? ""} aria-label="Drawing units"
          onChange={(e) => onChange({ ...value, units: e.target.value === "" ? null : Number(e.target.value) })}>
          {UNITS.map(([name, v]) => (
            <option key={name} value={v ?? ""}>{v === null ? `${name}${drawingUnits ? ` (${drawingUnits})` : " (it does not say: metres)"}` : name}</option>
          ))}
        </select>
      </label>

      {candidates.length > 0 && (
        <fieldset>
          <legend className="text-xs font-semibold text-slate-700">Likely</legend>
          {candidates.length > 1 && !candidates.some((c) => c.sure) && (
            <p className="text-[11px] text-amber-800">
              These numbers fit {candidates.length} places: choose the one where the site is (the map shows it).
            </p>
          )}
          <ul className="mt-1 space-y-1">
            {candidates.map((c) => (
              <li key={c.placement.code}>
                <label className={`flex cursor-pointer gap-2 rounded border px-2 py-1.5 ${code === c.placement.code ? "border-blue-500 bg-blue-50" : "border-slate-200 hover:bg-slate-50"}`}>
                  <input type="radio" name="crs" checked={code === c.placement.code} onChange={() => set(c.placement)} />
                  <span>
                    <span className="font-medium text-slate-900">{c.name}</span> <span className="text-xs text-slate-500">EPSG:{c.placement.code}</span>
                    <span className="block text-xs text-slate-600">{c.reason}; lands at {at(c.centre)}</span>
                    {c.also && c.also.length > 0 && (
                      <span className="block text-[11px] text-slate-400" title={c.also.join("\n")}>
                        Same place within 3 km: {c.also.slice(0, 3).join(", ")}{c.also.length > 3 ? `, +${c.also.length - 3} more` : ""}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}

      {zones.length > 0 && (
        <label className="block text-xs text-slate-600">
          UTM (WGS 84): the zone is not in the numbers — choose it by where it lands
          <select className={`mt-0.5 ${FIELD}`} value={zoneFor ? zoneFor.code : ""} aria-label="UTM zone"
            onChange={(e) => e.target.value && set({ kind: "epsg", code: Number(e.target.value) })}>
            <option value="">choose a zone…</option>
            {zones.map((z) => <option key={z.code} value={z.code}>Zone {z.zone} — lands at {at(z.centre)}</option>)}
          </select>
        </label>
      )}

      <div>
        <label className="block text-xs text-slate-600">
          Any coordinate system (EPSG code or name: “Red Belt”, “22992”, “Lambert”…)
          <input className={`mt-0.5 ${FIELD}`} value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search coordinate systems" />
        </label>
        {found.data && found.data.items.length > 0 && (
          <ul className="mt-1 max-h-40 overflow-y-auto rounded border border-slate-200 text-xs">
            {found.data.items.map((c) => (
              <li key={c.code}>
                <button type="button" onClick={() => { set({ kind: "epsg", code: c.code }); setQuery(""); }}
                  className={`block w-full px-2 py-1 text-left hover:bg-slate-50 ${code === c.code ? "bg-blue-50 font-semibold" : ""}`}>
                  EPSG:{c.code} {c.name}{c.area ? <span className="text-slate-500"> — {c.area}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        )}
        {code !== null && !candidates.some((c) => c.placement.code === code) && !zoneFor && (
          <p className="mt-1 text-xs text-slate-700">Chosen: EPSG:{code}{p?.kind === "epsg" && p.name ? ` ${p.name}` : ""}</p>
        )}
      </div>

      <fieldset className={`rounded border p-2 ${local ? "border-blue-500 bg-blue-50/40" : "border-slate-200"}`}>
        <legend className="px-1 text-xs font-semibold text-slate-700">
          <label className="inline-flex items-center gap-1.5">
            <input type="radio" name="crs" checked={!!local} onChange={() => set(localDefault)} />
            Local engineering coordinates
          </label>
        </legend>
        <p className="text-xs text-slate-600">
          A site grid with no map projection: say where one drawing point is on the ground, and which way the drawing faces.
          Click the map to put that point there.
        </p>
        {local && (
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
            {([["Drawing point x", 0], ["Drawing point y", 1]] as const).map(([label, i]) => (
              <label key={label}>{label}
                <input className={FIELD} type="number" value={local.anchor[i]} aria-label={label}
                  onChange={(e) => { const a = [...local.anchor] as [number, number]; a[i] = Number(e.target.value); set({ ...local, anchor: a }); }} />
              </label>
            ))}
            <label>Is at latitude
              <input className={FIELD} type="number" step={0.000001} value={local.lonlat[1]} aria-label="Latitude of the drawing point"
                onChange={(e) => set({ ...local, lonlat: [local.lonlat[0], Number(e.target.value)] })} />
            </label>
            <label>longitude
              <input className={FIELD} type="number" step={0.000001} value={local.lonlat[0]} aria-label="Longitude of the drawing point"
                onChange={(e) => set({ ...local, lonlat: [Number(e.target.value), local.lonlat[1]] })} />
            </label>
            <label className="col-span-2">Or paste a position (latitude, longitude)
              <span className="flex gap-1">
                <input className={FIELD} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="30.0444, 31.2357" aria-label="Paste a position" />
                <button type="button" className="rounded border border-slate-300 bg-white px-2"
                  onClick={() => { const q = parseLatLon(paste); if (q) { set({ ...local, lonlat: q }); setPaste(""); } }}>Use</button>
              </span>
            </label>
            <label>Drawing north turned
              <span className="flex items-center gap-1">
                <input className={FIELD} type="number" value={local.rotation} aria-label="Rotation in degrees clockwise"
                  onChange={(e) => set({ ...local, rotation: Number(e.target.value) })} />°
              </span>
            </label>
            <label>Scale
              <input className={FIELD} type="number" step={0.0001} value={local.scale} aria-label="Scale factor"
                onChange={(e) => set({ ...local, scale: Number(e.target.value) || 1 })} />
            </label>
          </div>
        )}
      </fieldset>
    </div>
  );
}
