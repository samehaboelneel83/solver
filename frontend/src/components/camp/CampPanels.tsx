/**
 * The camp editor's forms: every value a drawing carries, typed exactly.
 *
 * What the map draws by hand -- corners, doors -- can be set here to the
 * centimetre; what a drawing cannot show -- door capacities, zone depths, bed
 * types, the solve's goals -- is only set here.
 */
import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import type { CampBedType, CampDoor, CampDoorZone, CampObjectiveName, CampProblem, CampShape, Pt, Ring } from "../../api/camps";
import { area, freshName, length, parseLatLon } from "../../lib/campGeo";

const FIELD = "w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-sm";

/** A number typed freely, kept when it is one; empty is `null` when allowed. */
export function NumberField({
  value, onChange, label, nullable = false, min, step = 0.1, unit, className = "", hint, hideLabel = false,
}: {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  label: string;
  nullable?: boolean;
  min?: number;
  step?: number;
  unit?: string;
  className?: string;
  hint?: string;
  /** Read by a screen reader only: the column heading says it. */
  hideLabel?: boolean;
}) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => setText(value === null || value === undefined ? "" : String(value)), [value]);
  const commit = () => {
    const t = text.trim();
    if (t === "" && nullable) return onChange(null);
    const n = Number(t);
    if (t === "" || !Number.isFinite(n) || (min !== undefined && n < min)) {
      setText(value === null || value === undefined ? "" : String(value));
      return;
    }
    if (n !== value) onChange(n);
  };
  return (
    <label className={`block text-xs text-slate-600 ${className}`} title={hint}>
      <span className={hideLabel ? "sr-only" : ""}>{label}</span>
      <span className={`${hideLabel ? "" : "mt-0.5"} flex items-center gap-1`}>
        <input inputMode="decimal" value={text} step={step} onChange={(e) => setText(e.target.value)} onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); }} aria-label={label}
          placeholder={nullable ? "none" : undefined} className={FIELD} />
        {unit && <span className="shrink-0 text-slate-500">{unit}</span>}
      </span>
    </label>
  );
}

export function TextField({ value, onChange, label, className = "" }: { value: string; onChange: (v: string) => void; label: string; className?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => { if (text.trim() && text.trim() !== value) onChange(text.trim()); else setText(value); };
  return (
    <label className={`block text-xs text-slate-600 ${className}`}>
      {label}
      <input value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} aria-label={label}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); }} className={`mt-0.5 ${FIELD}`} maxLength={80} />
    </label>
  );
}

/** A ring's corners as numbers: edit, add after, remove. */
export function CoordTable({ ring, onChange, label }: { ring: Ring; onChange: (ring: Ring) => void; label: string }) {
  const set = (i: number, axis: 0 | 1, v: number | null) => {
    if (v === null) return;
    onChange(ring.map((p, k) => (k === i ? ((axis === 0 ? [v, p[1]] : [p[0], v]) as Pt) : p)));
  };
  return (
    <details className="mt-2 rounded border border-slate-200" open={ring.length <= 8}>
      <summary className="cursor-pointer px-2 py-1 text-xs font-medium text-slate-700">
        {label}: {ring.length} corners · {area(ring).toFixed(1)} m²
      </summary>
      <table className="w-full text-xs">
        <thead><tr className="text-slate-500"><th className="w-6">#</th><th>x (m east)</th><th>y (m north)</th><th className="w-14" /></tr></thead>
        <tbody>
          {ring.map((p, i) => (
            <tr key={i}>
              <td className="text-center text-slate-500">{i + 1}</td>
              <td className="p-0.5"><NumberField label={`Corner ${i + 1} x`} value={p[0]} onChange={(v) => set(i, 0, v)} hideLabel /></td>
              <td className="p-0.5"><NumberField label={`Corner ${i + 1} y`} value={p[1]} onChange={(v) => set(i, 1, v)} hideLabel /></td>
              <td className="whitespace-nowrap text-right">
                <button type="button" title="Add a corner after this one" aria-label={`Add a corner after ${i + 1}`}
                  className="rounded p-0.5 text-slate-500 hover:bg-slate-100"
                  onClick={() => {
                    const q = ring[(i + 1) % ring.length];
                    const mid: Pt = [Number(((p[0] + q[0]) / 2).toFixed(3)), Number(((p[1] + q[1]) / 2).toFixed(3))];
                    onChange([...ring.slice(0, i + 1), mid, ...ring.slice(i + 1)]);
                  }}><Plus className="h-3.5 w-3.5" /></button>
                <button type="button" title="Remove this corner" aria-label={`Remove corner ${i + 1}`} disabled={ring.length <= 3}
                  className="rounded p-0.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
                  onClick={() => onChange(ring.filter((_, k) => k !== i))}><Trash2 className="h-3.5 w-3.5" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export function DoorPanel({
  door, zone, onDoor, onZone, onRename, taken,
}: {
  door: CampDoor;
  zone: CampDoorZone;
  onDoor: (d: CampDoor) => void;
  onZone: (z: CampDoorZone) => void;
  onRename: (id: string) => void;
  taken: string[];
}) {
  const width = length(door.a, door.b);
  const horizontal = door.a[1] === door.b[1];
  return (
    <div className="space-y-2">
      <TextField label="Door name" value={door.id} onChange={(v) => { if (!taken.includes(v)) onRename(v); }} />
      <div className="grid grid-cols-2 gap-2">
        <NumberField label={horizontal ? "From x" : "From y"} unit="m" value={horizontal ? door.a[0] : door.a[1]}
          onChange={(v) => v !== null && onDoor({ ...door, a: horizontal ? [v, door.a[1]] : [door.a[0], v] })} />
        <NumberField label={horizontal ? "To x" : "To y"} unit="m" value={horizontal ? door.b[0] : door.b[1]}
          onChange={(v) => v !== null && onDoor({ ...door, b: horizontal ? [v, door.b[1]] : [door.b[0], v] })} />
      </div>
      <p className="text-xs text-slate-500">
        {width.toFixed(2)} m wide, on the {horizontal ? "horizontal" : "vertical"} wall at {horizontal ? `y ${door.a[1]}` : `x ${door.a[0]}`} m.
        Drag its ends on the map to slide it along the wall.
      </p>
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Capacity (most beds)" nullable min={1} step={1} value={door.capacity ?? null}
          hint="The most beds this door may serve in an evacuation; empty for no limit"
          onChange={(v) => onDoor({ ...door, capacity: v === null ? null : Math.round(v) })} />
        <NumberField label="Frame depth" unit="m" min={0.05} value={door.depth ?? 0.3}
          onChange={(v) => v !== null && onDoor({ ...door, depth: v })} />
      </div>
      <fieldset className="rounded border border-slate-200 p-2">
        <legend className="px-1 text-xs font-medium text-slate-700">Clear zone inside the door</legend>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Depth" unit="m" min={0.5} value={zone.depth ?? 2} onChange={(v) => v !== null && onZone({ ...zone, depth: v })} />
          <NumberField label="May grow to" unit="m" min={0.5} value={zone.max_depth ?? 4} onChange={(v) => v !== null && onZone({ ...zone, max_depth: v })} />
          <NumberField label="In steps of" unit="m" min={0.25} value={zone.step ?? 1} onChange={(v) => v !== null && onZone({ ...zone, step: v })} />
          <NumberField label="Wider each side by" unit="m" min={0} value={zone.margin ?? 0.5} onChange={(v) => v !== null && onZone({ ...zone, margin: v })} />
          <NumberField label="Room per bed served" unit="m²" nullable min={0.01} value={zone.area_per_bed === undefined ? 0.5 : zone.area_per_bed}
            hint="Assembly room the zone must give each bed using this door; empty for no rule"
            onChange={(v) => onZone({ ...zone, area_per_bed: v })} className="col-span-2" />
        </div>
      </fieldset>
    </div>
  );
}

export function ShapePanel({
  shape, kind, onChange, onRename, taken, bedTypes, onAssign,
}: {
  shape: CampShape;
  kind: "obstacles" | "prohibited" | "placement_zones";
  onChange: (s: CampShape) => void;
  onRename: (id: string) => void;
  taken: string[];
  bedTypes?: CampBedType[];
  onAssign?: (typeId: string, on: boolean) => void;
}) {
  return (
    <div className="space-y-2">
      <TextField label="Name" value={shape.id} onChange={(v) => { if (!taken.includes(v)) onRename(v); }} />
      {kind === "obstacles" && (
        <TextField label="What it is" value={shape.kind ?? "closed"} onChange={(v) => onChange({ ...shape, kind: v })} />
      )}
      {kind === "placement_zones" && bedTypes && onAssign && (
        <fieldset className="rounded border border-slate-200 p-2 text-xs">
          <legend className="px-1 font-medium text-slate-700">Bed types that must go here</legend>
          {bedTypes.map((b) => (
            <label key={b.id} className="mr-3 inline-flex items-center gap-1">
              <input type="checkbox" checked={b.zone === shape.id} onChange={(e) => onAssign(b.id, e.target.checked)} /> {b.id}
            </label>
          ))}
        </fieldset>
      )}
      <CoordTable label="Corners" ring={shape.ring} onChange={(ring) => onChange({ ...shape, ring })} />
    </div>
  );
}

function sizesText(sizes: Pt[] | undefined): string {
  return (sizes ?? []).map(([l, w]) => `${l}x${w}`).join("; ");
}

function parseSizes(text: string): Pt[] | null {
  const parts = text.split(/[;,]/).map((s) => s.trim()).filter(Boolean);
  const out: Pt[] = [];
  for (const part of parts) {
    const m = /^(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)$/i.exec(part);
    if (!m) return null;
    out.push([Number(m[1]), Number(m[2])]);
  }
  return out;
}

export function BedTypesPanel({ problem, onChange }: { problem: CampProblem; onChange: (types: CampBedType[]) => void }) {
  const types = problem.bed_types;
  const set = (i: number, patch: Partial<CampBedType>) => onChange(types.map((t, k) => (k === i ? { ...t, ...patch } : t)));
  const [sizeText, setSizeText] = useState<Record<number, string>>({});
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Length runs along the bed, width across it. A range lets the solver shorten or narrow a bed to fit more,
        at a small cost; list the sizes it may use.
      </p>
      {types.map((t, i) => (
        <fieldset key={i} className="rounded-lg border border-slate-200 p-2" data-testid="bed-type">
          <legend className="flex items-center gap-2 px-1 text-sm font-medium text-slate-800">
            {t.id}
            <button type="button" aria-label={`Remove bed type ${t.id}`} disabled={types.length <= 1}
              className="rounded p-0.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
              onClick={() => onChange(types.filter((_, k) => k !== i))}><Trash2 className="h-3.5 w-3.5" /></button>
          </legend>
          <div className="grid grid-cols-3 gap-2">
            <TextField label="Name" value={t.id} onChange={(v) => { if (!types.some((x) => x.id === v)) set(i, { id: v }); }} />
            <NumberField label="Length" unit="m" min={0.3} value={t.length} onChange={(v) => v !== null && set(i, { length: v })} />
            <NumberField label="Width" unit="m" min={0.3} value={t.width} onChange={(v) => v !== null && set(i, { width: v })} />
            <NumberField label="Shortest" unit="m" nullable min={0.3} value={t.min_length ?? null} onChange={(v) => set(i, { min_length: v })} />
            <NumberField label="Longest" unit="m" nullable min={0.3} value={t.max_length ?? null} onChange={(v) => set(i, { max_length: v })} />
            <NumberField label="Gap beside" unit="m" min={0} value={t.side_gap ?? 0.1} onChange={(v) => v !== null && set(i, { side_gap: v })} />
            <NumberField label="Narrowest" unit="m" nullable min={0.3} value={t.min_width ?? null} onChange={(v) => set(i, { min_width: v })} />
            <NumberField label="Widest" unit="m" nullable min={0.3} value={t.max_width ?? null} onChange={(v) => set(i, { max_width: v })} />
            <NumberField label="Priority" min={0} value={t.priority ?? 1} onChange={(v) => v !== null && set(i, { priority: v })}
              hint="How much one bed of this type counts in the bed total" />
            <NumberField label="At least" step={1} min={0} value={t.min_count ?? 0} onChange={(v) => v !== null && set(i, { min_count: Math.round(v) })} />
            <NumberField label="At most" step={1} nullable min={0} value={t.max_count ?? null} onChange={(v) => set(i, { max_count: v === null ? null : Math.round(v) })} />
            <label className="block text-xs text-slate-600">
              Must go in
              <select value={t.zone ?? ""} onChange={(e) => set(i, { zone: e.target.value || null })} className={`mt-0.5 ${FIELD}`}>
                <option value="">anywhere</option>
                {problem.placement_zones.map((z) => <option key={z.id} value={z.id}>{z.id}</option>)}
              </select>
            </label>
          </div>
          <label className="mt-2 block text-xs text-slate-600">
            Other sizes it may take (length x width; …)
            <input value={sizeText[i] ?? sizesText(t.sizes)} aria-label={`Other sizes for ${t.id}`}
              onChange={(e) => setSizeText({ ...sizeText, [i]: e.target.value })}
              onBlur={() => {
                const parsed = parseSizes(sizeText[i] ?? sizesText(t.sizes));
                if (parsed) set(i, { sizes: parsed });
                setSizeText((s) => { const n = { ...s }; delete n[i]; return n; });
              }}
              placeholder="e.g. 2.0x0.9" className={`mt-0.5 ${FIELD}`} />
          </label>
          <label className="mt-2 flex items-center gap-1.5 text-xs text-slate-700">
            <input type="checkbox" checked={t.rotation ?? true} onChange={(e) => set(i, { rotation: e.target.checked })} />
            May be turned 90°
          </label>
        </fieldset>
      ))}
      <button type="button" className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm hover:bg-slate-50"
        onClick={() => onChange([...types, { id: freshName("bed", types.map((t) => t.id)), length: 2.0, width: 0.9 }])}>
        <Plus className="h-4 w-4" aria-hidden /> Add a bed type
      </button>
    </div>
  );
}

const GOALS: Record<CampObjectiveName, string> = {
  beds: "Most beds",
  distance: "Shortest walks to the doors",
  corridor: "Least corridor area",
  modifications: "Fewest resized beds and grown door zones",
};

export function SettingsPanel({
  problem, onChange, onName, name,
}: {
  problem: CampProblem;
  onChange: (p: CampProblem) => void;
  onName: (name: string) => void;
  name: string;
}) {
  const [where, setWhere] = useState("");
  const order = problem.objectives.order;
  const move = (i: number, by: number) => {
    const next = [...order];
    const [item] = next.splice(i, 1);
    next.splice(i + by, 0, item);
    onChange({ ...problem, objectives: { ...problem.objectives, order: next } });
  };
  const objectives = problem.objectives;
  return (
    <div className="space-y-3">
      <TextField label="Camp name" value={name} onChange={onName} />
      <fieldset className="rounded border border-slate-200 p-2">
        <legend className="px-1 text-xs font-medium text-slate-700">Where the camp is</legend>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Latitude of (0, 0)" step={0.000001} value={problem.origin_lonlat[1]}
            onChange={(v) => v !== null && Math.abs(v) <= 90 && onChange({ ...problem, origin_lonlat: [problem.origin_lonlat[0], v] })} />
          <NumberField label="Longitude of (0, 0)" step={0.000001} value={problem.origin_lonlat[0]}
            onChange={(v) => v !== null && Math.abs(v) <= 180 && onChange({ ...problem, origin_lonlat: [v, problem.origin_lonlat[1]] })} />
        </div>
        <label className="mt-2 block text-xs text-slate-600">
          Paste a position (latitude, longitude)
          <span className="mt-0.5 flex gap-1">
            <input value={where} onChange={(e) => setWhere(e.target.value)} placeholder="e.g. 30.0444, 31.2357" className={FIELD} aria-label="Position to paste" />
            <button type="button" className="rounded border border-slate-300 bg-white px-2 text-xs hover:bg-slate-50"
              onClick={() => { const p = parseLatLon(where); if (p) { onChange({ ...problem, origin_lonlat: p }); setWhere(""); } }}>Go</button>
          </span>
        </label>
        <p className="mt-1 text-xs text-slate-500">Or choose “Place on map” in the toolbar and drag the camp over the imagery.</p>
      </fieldset>
      <fieldset className="rounded border border-slate-200 p-2">
        <legend className="px-1 text-xs font-medium text-slate-700">Corridors and grid</legend>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Corridors at least" unit="m" min={0.5} value={problem.corridor.min_width}
            onChange={(v) => v !== null && onChange({ ...problem, corridor: { ...problem.corridor, min_width: v } })} />
          <label className="block text-xs text-slate-600">
            Grid
            <select value={problem.grid} onChange={(e) => onChange({ ...problem, grid: Number(e.target.value) })} className={`mt-0.5 ${FIELD}`}>
              <option value={0.25}>0.25 m (fine, slower)</option>
              <option value={0.5}>0.5 m</option>
              <option value={1}>1 m (coarse, fast)</option>
            </select>
          </label>
          <label className="col-span-2 block text-xs text-slate-600">
            A bed is used from
            <select value={problem.corridor.access} className={`mt-0.5 ${FIELD}`}
              onChange={(e) => onChange({ ...problem, corridor: { ...problem.corridor, access: e.target.value as "long_sides" | "any_side" } })}>
              <option value="long_sides">a long side</option>
              <option value="any_side">any side</option>
            </select>
          </label>
        </div>
      </fieldset>
      <fieldset className="rounded border border-slate-200 p-2">
        <legend className="px-1 text-xs font-medium text-slate-700">Goals</legend>
        <label className="block text-xs text-slate-600">
          How they combine
          <select value={objectives.mode} className={`mt-0.5 ${FIELD}`}
            onChange={(e) => onChange({ ...problem, objectives: { ...objectives, mode: e.target.value as "lexicographic" | "weighted" } })}>
            <option value="lexicographic">In order: each goal kept while the next is improved</option>
            <option value="weighted">Weighted together</option>
          </select>
        </label>
        <ol className="mt-2 space-y-1">
          {order.map((g, i) => (
            <li key={g} className="flex items-center gap-1 rounded bg-slate-50 px-2 py-1 text-xs">
              <span className="w-4 text-slate-500">{i + 1}.</span>
              <span className="flex-1 text-slate-800">{GOALS[g]}</span>
              {objectives.mode === "weighted" && (
                <NumberField label={`Weight of ${GOALS[g]}`} value={objectives.weights[g] ?? 1} min={0} className="w-20" hideLabel
                  onChange={(v) => v !== null && onChange({ ...problem, objectives: { ...objectives, weights: { ...objectives.weights, [g]: v } } })} />
              )}
              <button type="button" aria-label={`Move ${GOALS[g]} up`} disabled={i === 0} onClick={() => move(i, -1)}
                className="rounded p-0.5 hover:bg-slate-200 disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /></button>
              <button type="button" aria-label={`Move ${GOALS[g]} down`} disabled={i === order.length - 1} onClick={() => move(i, 1)}
                className="rounded p-0.5 hover:bg-slate-200 disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /></button>
            </li>
          ))}
        </ol>
        {objectives.mode === "lexicographic" && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <NumberField label="Walks may give back" unit="%" min={0} value={Math.round((objectives.tolerance.distance ?? 0.02) * 1000) / 10}
              onChange={(v) => v !== null && onChange({ ...problem, objectives: { ...objectives, tolerance: { ...objectives.tolerance, distance: v / 100 } } })} />
            <NumberField label="Corridors may give back" unit="%" min={0} value={Math.round((objectives.tolerance.corridor ?? 0.02) * 1000) / 10}
              onChange={(v) => v !== null && onChange({ ...problem, objectives: { ...objectives, tolerance: { ...objectives.tolerance, corridor: v / 100 } } })} />
          </div>
        )}
        <label className="mt-2 flex items-center gap-1.5 text-xs text-slate-700">
          <input type="checkbox" checked={objectives.trade_beds}
            onChange={(e) => onChange({ ...problem, objectives: { ...objectives, trade_beds: e.target.checked } })} />
          Later goals may cost beds
        </label>
      </fieldset>
    </div>
  );
}
