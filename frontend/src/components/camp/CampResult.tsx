/**
 * A camp's layout on the map, and what it says beside the map.
 *
 * `ResultLayers` draws the stored answer (`GET /camp-solves/{id}`): door
 * zones as the solver sized them, corridors, closed and no-bed areas, every
 * bed coloured by its type, its door or its walk, and the walking route of
 * the bed under the pointer. `ResultPanel` asks for a solve, follows it while
 * the worker runs it, and shows the counts, door loads, the independent
 * checks and the downloads: GeoJSON in WGS84 for any GIS, local metres for
 * CAD, the report and a standalone map.
 */
import { useEffect } from "react";
import { CheckCircle2, Download, XCircle } from "lucide-react";
import {
  downloadFrom, useCamp, type CampOptions, type CampPlan, type CampSolve, type GeoFeature, type Pt,
} from "../../api/camps";
import type { At } from "./CampMap";

export type ColourBy = "type" | "door" | "walk";
type Result = NonNullable<CampSolve["result"]>;

export const PALETTE = [
  "#2563eb", "#d97706", "#059669", "#db2777", "#7c3aed", "#0891b2", "#65a30d", "#dc2626", "#4f46e5", "#ca8a04",
];

function polygonPath(at: At, geometry: GeoFeature["geometry"]): string {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates as Pt[][]]
    : geometry.type === "MultiPolygon" ? (geometry.coordinates as Pt[][][]) : [];
  let d = "";
  for (const rings of polys)
    for (const ring of rings)
      d += ring.map((p, i) => `${i ? "L" : "M"}${at(p)[0].toFixed(1)},${at(p)[1].toFixed(1)}`).join("") + "Z";
  return d;
}

function linePath(at: At, geometry: GeoFeature["geometry"]): string {
  const lines = geometry.type === "LineString" ? [geometry.coordinates as Pt[]]
    : geometry.type === "MultiLineString" ? (geometry.coordinates as Pt[][]) : [];
  return lines.map((line) => line.map((p, i) => `${i ? "L" : "M"}${at(p)[0].toFixed(1)},${at(p)[1].toFixed(1)}`).join("")).join("");
}

function walkColour(t: number): string {
  // Light to dark blue: short walks pale, long walks deep.
  const a = [219, 234, 254], b = [30, 64, 175];
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * Math.max(0, Math.min(1, t))));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function colourKeys(result: Result, by: ColourBy): string[] {
  const beds = result.output.features.filter((f) => f.properties.layer === "bed");
  const key = by === "type" ? "bed_type" : "door";
  return [...new Set(beds.map((f) => String(f.properties[key] ?? "?")))].sort();
}

function bedColour(result: Result, by: ColourBy, f: GeoFeature, walkRange: [number, number]): string {
  if (by === "walk") {
    const w = Number(f.properties.walk_m ?? 0);
    return walkColour((w - walkRange[0]) / Math.max(walkRange[1] - walkRange[0], 1e-9));
  }
  const keys = colourKeys(result, by);
  return PALETTE[keys.indexOf(String(f.properties[by === "type" ? "bed_type" : "door"] ?? "?")) % PALETTE.length];
}

function walkRangeOf(result: Result): [number, number] {
  const walks = result.output.features.filter((f) => f.properties.layer === "bed").map((f) => Number(f.properties.walk_m ?? 0));
  return walks.length ? [Math.min(...walks), Math.max(...walks)] : [0, 1];
}

export function ResultLayers({
  at, result, colourBy, hoverBed, onHoverBed, showPaths, labels,
}: {
  at: At;
  result: Result;
  colourBy: ColourBy;
  hoverBed: string | null;
  onHoverBed: (id: string | null) => void;
  showPaths: boolean;
  labels: boolean;
}) {
  const feats = result.output.features;
  const range = walkRangeOf(result);
  const of = (layer: string) => feats.filter((f) => f.properties.layer === layer);
  return (
    <g>
      {of("door_zone").map((f, i) => (
        <path key={`dz-${i}`} d={polygonPath(at, f.geometry)} fill="rgba(245,158,11,0.3)" stroke="#b45309" strokeWidth={1} />
      ))}
      {of("corridor").map((f, i) => (
        <path key={`c-${i}`} d={polygonPath(at, f.geometry)} fill="rgba(254,243,199,0.85)" stroke="#d6a84a" strokeWidth={0.8} fillRule="evenodd" />
      ))}
      {of("prohibited").map((f, i) => (
        <path key={`p-${i}`} d={polygonPath(at, f.geometry)} fill="url(#camp-hatch)" stroke="#b91c1c" strokeWidth={1.2} />
      ))}
      {of("obstacle").map((f, i) => (
        <path key={`o-${i}`} d={polygonPath(at, f.geometry)} fill="rgba(71,85,105,0.9)" stroke="#1e293b" strokeWidth={1.2} />
      ))}
      {of("bed").map((f) => {
        const id = String(f.properties.id);
        const on = hoverBed === id;
        return (
          <path key={`b-${id}`} d={polygonPath(at, f.geometry)} fill={bedColour(result, colourBy, f, range)}
            stroke={on ? "#0f172a" : "#ffffff"} strokeWidth={on ? 2.5 : 0.8}
            onPointerEnter={() => onHoverBed(id)} onPointerLeave={() => onHoverBed(null)} data-testid="layout-bed">
            <title>{`${id}: ${f.properties.bed_type} ${f.properties.size}${f.properties.resized ? " (resized)" : ""} · door ${f.properties.door} · ${f.properties.walk_m} m walk`}</title>
          </path>
        );
      })}
      {of("path").filter((f) => showPaths || f.properties.bed === hoverBed).map((f) => (
        <path key={`r-${String(f.properties.bed)}`} d={linePath(at, f.geometry)} fill="none"
          stroke={f.properties.bed === hoverBed ? "#be123c" : "rgba(190,18,60,0.35)"} strokeWidth={f.properties.bed === hoverBed ? 2.5 : 1}
          strokeDasharray={f.properties.bed === hoverBed ? "6 3" : undefined} pointerEvents="none" />
      ))}
      {labels && of("door_zone").map((f, i) => {
        const ring = (f.geometry.coordinates as Pt[][])[0] ?? [];
        if (!ring.length) return null;
        const c: Pt = [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length];
        const [x, y] = at(c);
        return (
          <text key={`dzl-${i}`} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize={10} fill="#92400e"
            stroke="#fff" strokeWidth={3} paintOrder="stroke" pointerEvents="none">
            {String(f.properties.beds_served)} beds
          </text>
        );
      })}
    </g>
  );
}

export function ResultLegend({ result, colourBy }: { result: Result; colourBy: ColourBy }) {
  const range = walkRangeOf(result);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700" aria-label="Legend">
      {colourBy === "walk" ? (
        <span className="flex items-center gap-1.5">
          Walk to the door {range[0].toFixed(1)} m
          <span className="inline-block h-2.5 w-24 rounded" style={{ background: `linear-gradient(90deg, ${walkColour(0)}, ${walkColour(1)})` }} />
          {range[1].toFixed(1)} m
        </span>
      ) : colourKeys(result, colourBy).map((k, i) => (
        <span key={k} className="flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
          {colourBy === "door" ? `door ${k}` : k}
        </span>
      ))}
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 border border-amber-500 bg-amber-100" /> corridor</span>
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 border border-amber-700 bg-amber-300/60" /> door zone</span>
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 bg-slate-600" /> closed</span>
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 border border-red-700 bg-red-100" /> no beds</span>
      <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-rose-700" /> route of the bed under the pointer</span>
    </div>
  );
}

const SOLVERS: [CampOptions["solver"], string][] = [
  ["cpsat", "CP-SAT (best)"],
  ["highs", "HiGHS"],
  ["scip", "SCIP"],
  ["cbc", "CBC"],
  ["heuristic", "Quick layout (seconds, not optimal)"],
];

const STATUS_TEXT: Record<CampSolve["status"], string> = {
  queued: "Waiting for the worker",
  running: "Laying out",
  done: "Done",
  failed: "Failed",
  cancelled: "Stopped",
};

function Tile({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "green" | "red" }) {
  const colour = tone === "green" ? "text-emerald-800" : tone === "red" ? "text-red-800" : "text-slate-900";
  return (
    <div className="rounded bg-slate-50 px-2 py-1.5">
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className={`font-mono text-base font-semibold ${colour}`}>{value}</dd>
    </div>
  );
}

const FILES: [string, string][] = [
  ["output_wgs84.geojson", "Layout — GeoJSON (WGS84, for QGIS, ArcGIS, Google Earth Pro)"],
  ["input_wgs84.geojson", "Camp as drawn — GeoJSON (WGS84)"],
  ["output_local.geojson", "Layout — GeoJSON (local metres, for CAD)"],
  ["input_local.geojson", "Camp as drawn — GeoJSON (local metres)"],
  ["viewer.html", "Standalone map to share (.html)"],
  ["report.json", "Report (.json)"],
  ["layout.json", "Layout record (.json)"],
];

export function ResultPanel({
  plan, options, onOptions, solve, onPickSolve, onCancel, onShow, colourBy, onColourBy, hoverBed, canSolve, onSolve,
}: {
  plan: CampPlan;
  options: CampOptions;
  onOptions: (o: CampOptions) => void;
  solve: CampSolve | null;
  onPickSolve: (id: number) => void;
  onCancel: () => void;
  onShow: () => void;
  colourBy: ColourBy;
  onColourBy: (c: ColourBy) => void;
  hoverBed: string | null;
  canSolve: boolean;
  onSolve: () => void;
}) {
  const fresh = useCamp(plan.id);
  const refetch = fresh.refetch;
  useEffect(() => { void refetch(); }, [solve?.status, refetch]);
  const solves = fresh.data?.solves ?? plan.solves;
  const running = solve && (solve.status === "queued" || solve.status === "running");
  const result = solve?.result ?? null;
  const report = result?.report;
  const bed = hoverBed && result ? result.output.features.find((f) => f.properties.layer === "bed" && f.properties.id === hoverBed) : null;
  const capacity = Object.fromEntries((solve?.problem.doors ?? []).map((d) => [d.id, d.capacity ?? null]));

  return (
    <div className="space-y-3">
      <section className="rounded-lg border border-slate-200 p-2" aria-label="How to lay it out">
        <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
          <label className="col-span-2 block">
            Solver
            <select value={options.solver} onChange={(e) => onOptions({ ...options, solver: e.target.value as CampOptions["solver"] })}
              className="mt-0.5 w-full rounded border border-slate-300 bg-white px-1.5 py-1 text-sm">
              {SOLVERS.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
            </select>
          </label>
          <label className="block">
            Time for the most beds
            <span className="mt-0.5 flex items-center gap-1">
              <input type="number" min={5} max={1800} value={options.beds_seconds} disabled={options.solver === "heuristic"}
                onChange={(e) => onOptions({ ...options, beds_seconds: Math.max(5, Number(e.target.value) || 5) })}
                className="w-full rounded border border-slate-300 px-1.5 py-1 text-sm" />s
            </span>
          </label>
          <label className="block">
            Time for each later goal
            <span className="mt-0.5 flex items-center gap-1">
              <input type="number" min={5} max={1800} value={options.seconds} disabled={options.solver === "heuristic"}
                onChange={(e) => onOptions({ ...options, seconds: Math.max(5, Number(e.target.value) || 5) })}
                className="w-full rounded border border-slate-300 px-1.5 py-1 text-sm" />s
            </span>
          </label>
        </div>
        <button type="button" disabled={!canSolve || !!running} onClick={onSolve}
          className="mt-2 w-full rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          Lay out camp
        </button>
      </section>

      {solve && (
        <section aria-label="This layout" className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className={`rounded-full px-2 py-0.5 font-medium ${solve.status === "done" ? "bg-emerald-50 text-emerald-800" : solve.status === "failed" ? "bg-red-50 text-red-800" : "bg-blue-50 text-blue-800"}`}>
              {STATUS_TEXT[solve.status]}
            </span>
            <span className="text-slate-500">Layout #{solve.id} · {solve.options.solver} · {solve.seconds.toFixed(0)} s</span>
          </div>
          {running && (
            <>
              <div className="h-2 overflow-hidden rounded bg-slate-100" role="progressbar" aria-label="Time used"
                aria-valuemin={0} aria-valuemax={solve.deadline_seconds} aria-valuenow={Math.round(solve.seconds)}>
                <div className="h-full bg-blue-600 transition-all" style={{ width: `${Math.min(100, (solve.seconds / Math.max(1, solve.options.beds_seconds + 3 * solve.options.seconds + 30)) * 100)}%` }} />
              </div>
              <pre className="max-h-36 overflow-y-auto whitespace-pre-wrap rounded bg-slate-900 p-2 font-mono text-[11px] leading-snug text-slate-100">
                {solve.progress.slice(-10).join("\n") || "Waiting for the worker to start…"}
              </pre>
              <button type="button" onClick={onCancel} className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50">Stop</button>
            </>
          )}
          {solve.status === "failed" && <p role="alert" className="rounded bg-red-50 p-2 text-xs text-red-800">{solve.error}</p>}
          {report && result && (
            <>
              <dl className="grid grid-cols-3 gap-2 text-center">
                <Tile label="Beds" value={String(report.beds)} />
                <Tile label="Checks" value={report.validation.valid ? "all pass" : "failed"} tone={report.validation.valid ? "green" : "red"} />
                <Tile label="Longest walk" value={`${report.validation.walk_max_m} m`} />
                <Tile label="Mean walk" value={`${report.validation.walk_mean_m} m`} />
                <Tile label="Resized beds" value={String(report.resized_beds)} />
                <Tile label="Quick start" value={`${report.stage0_beds} beds`} />
              </dl>
              <p className="text-xs text-slate-600">
                {Object.entries(report.beds_by_type).map(([t, n]) => `${n} ${t}`).join(", ")}
              </p>
              <div className="flex items-center gap-2 text-xs text-slate-600">
                Colour beds by
                {(["type", "door", "walk"] as ColourBy[]).map((c) => (
                  <label key={c} className="inline-flex items-center gap-1">
                    <input type="radio" name="colour-by" checked={colourBy === c} onChange={() => { onColourBy(c); onShow(); }} />
                    {c === "type" ? "type" : c === "door" ? "door" : "walk"}
                  </label>
                ))}
              </div>
              {bed ? (
                <p className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-900">
                  <strong>{String(bed.properties.id)}</strong>: {String(bed.properties.bed_type)} {String(bed.properties.size)}
                  {bed.properties.resized ? " (resized)" : ""}, to door {String(bed.properties.door)}, {String(bed.properties.walk_m)} m walk
                </p>
              ) : <p className="text-xs text-slate-400">Point at a bed on the map to see its route.</p>}
              <table className="w-full text-xs">
                <caption className="mb-1 text-left font-semibold text-slate-700">Doors</caption>
                <thead><tr className="text-left text-slate-500"><th>Door</th><th>Beds</th><th>Most</th><th>Zone</th></tr></thead>
                <tbody>
                  {Object.entries(report.validation.door_loads).map(([d, n]) => {
                    const cap = capacity[d];
                    return (
                      <tr key={d} className="border-t border-slate-100">
                        <td className="py-0.5 font-medium">{d}</td>
                        <td>{n}</td>
                        <td className={cap !== null && n > cap ? "text-red-700" : ""}>{cap ?? "any"}</td>
                        <td>{report.zone_depth_m[d] !== undefined ? `${report.zone_depth_m[d]} m` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <details>
                <summary className="cursor-pointer text-xs font-semibold text-slate-700">Independent checks ({report.validation.checks.filter((c) => c.ok).length}/{report.validation.checks.length})</summary>
                <ul className="mt-1 space-y-0.5">
                  {report.validation.checks.map((c) => (
                    <li key={c.name} className="flex gap-1.5 text-xs">
                      {c.ok ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-label="passed" /> : <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600" aria-label="failed" />}
                      <span><span className="text-slate-800">{c.name}</span> <span className="text-slate-500">{c.detail}</span></span>
                    </li>
                  ))}
                </ul>
              </details>
              <details>
                <summary className="cursor-pointer text-xs font-semibold text-slate-700">Solver stages</summary>
                <table className="mt-1 w-full text-xs">
                  <thead><tr className="text-left text-slate-500"><th>Goal</th><th>Status</th><th>Value</th><th>s</th></tr></thead>
                  <tbody>
                    {report.stages.map((s, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td>{s.objective}</td><td>{s.status}</td>
                        <td>{s.value !== undefined && s.value !== null ? Number(s.value).toFixed(1) : "—"}</td>
                        <td>{s.seconds !== undefined ? Number(s.seconds).toFixed(0) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
              <section aria-label="Downloads">
                <h3 className="text-xs font-semibold text-slate-700">Download</h3>
                <ul className="mt-1 space-y-0.5">
                  {FILES.map(([file, text]) => (
                    <li key={file}>
                      <button type="button" onClick={() => void downloadFrom(`/api/v1/camp-solves/${solve.id}/files/${file}`)}
                        className="inline-flex items-center gap-1 text-left text-xs text-blue-700 hover:underline">
                        <Download className="h-3.5 w-3.5 shrink-0" aria-hidden /> {text}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            </>
          )}
        </section>
      )}

      {solves.length > 0 && (
        <section aria-label="Earlier layouts">
          <h3 className="text-xs font-semibold text-slate-700">Layouts of this camp</h3>
          <ul className="mt-1 divide-y divide-slate-100 rounded border border-slate-200">
            {solves.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => onPickSolve(s.id)}
                  className={`flex w-full items-center justify-between px-2 py-1 text-left text-xs ${solve?.id === s.id ? "bg-blue-50 font-semibold" : "hover:bg-slate-50"}`}>
                  <span>#{s.id} · {s.options.solver}</span>
                  <span className="text-slate-500">
                    {s.status === "done" ? `${s.beds} beds${s.valid ? "" : ", checks failed"}` : STATUS_TEXT[s.status]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
