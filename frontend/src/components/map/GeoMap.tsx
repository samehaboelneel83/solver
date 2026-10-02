/**
 * Any GeoJSON on a map (improvement plan 1.4 and 3.1): points, lines, areas,
 * each with its own colour, size and label, over the workspace's basemaps.
 * Used for records that have a shape and for any run's answer -- it knows
 * nothing about what the places are.
 *
 * SVG, so every mark carries its own tooltip; fine up to a few thousand
 * marks, which is what a plan's places are.
 */
import { useMemo, useState } from "react";
import { useSiteBasemap } from "./SiteMap";
import { fitView, tileUrl, type Basemap, type View } from "../../lib/tiles";

export type GeoGeometry =
  | { type: "Point"; coordinates: number[] }
  | { type: "LineString"; coordinates: number[][] }
  | { type: "MultiLineString"; coordinates: number[][][] }
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] };

export type GeoMark = {
  id: string;
  geometry: GeoGeometry;
  colour: string;
  /** Point radius in pixels, or line width. */
  size?: number;
  /** Fill opacity of an area (0..1); a point is always solid. */
  fill?: number;
  dashed?: boolean;
  title: string;
  /** Drawn beside the mark when shown. */
  label?: string;
  layer: string;
  /** A mark that can be picked (opened); without it the mark is only shown. */
  pickable?: boolean;
};

const WIDTH = 720;
const HEIGHT = 460;

function positions(g: GeoGeometry): number[][] {
  switch (g.type) {
    case "Point": return [g.coordinates];
    case "LineString": return g.coordinates;
    case "MultiLineString": return g.coordinates.flat();
    case "Polygon": return g.coordinates.flat();
    case "MultiPolygon": return g.coordinates.flat(2);
  }
}

function frameOf(marks: GeoMark[], basemap: Basemap | null): { at: (p: number[]) => number[]; tiles: View["tiles"] } | null {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const m of marks)
    for (const [x, y] of positions(m.geometry)) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  if (!Number.isFinite(minX)) return null;
  // A single point, or all on one spot: open a small window around it.
  if (maxX - minX < 1e-6) { minX -= 0.005; maxX += 0.005; }
  if (maxY - minY < 1e-6) { minY -= 0.005; maxY += 0.005; }
  const padX = (maxX - minX) * 0.06, padY = (maxY - minY) * 0.06;
  [minX, maxX, minY, maxY] = [minX - padX, maxX + padX, minY - padY, maxY + padY];
  if (basemap) {
    const view = fitView({ west: minX, south: minY, east: maxX, north: maxY }, WIDTH, HEIGHT, basemap);
    return { at: ([x, y]: number[]) => view.project(x, y), tiles: view.tiles };
  }
  const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180);
  const scale = Math.min(WIDTH / ((maxX - minX) * k || 1), HEIGHT / (maxY - minY || 1));
  const offX = (WIDTH - (maxX - minX) * k * scale) / 2, offY = (HEIGHT - (maxY - minY) * scale) / 2;
  return { at: ([x, y]: number[]) => [offX + (x - minX) * k * scale, HEIGHT - offY - (y - minY) * scale], tiles: [] };
}

function path(points: number[][], at: (p: number[]) => number[], close: boolean): string {
  return points.map((p, i) => {
    const [x, y] = at(p);
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ") + (close ? "Z" : "");
}

function Mark({ mark, at, showLabel }: { mark: GeoMark; at: (p: number[]) => number[]; showLabel: boolean }) {
  const g = mark.geometry;
  if (g.type === "Point") {
    const [x, y] = at(g.coordinates);
    return (
      <g>
        <circle cx={x} cy={y} r={mark.size ?? 5} fill={mark.colour} stroke="#fff" strokeWidth={1.2}>
          <title>{mark.title}</title>
        </circle>
        {showLabel && mark.label && (
          <text x={x + (mark.size ?? 5) + 3} y={y + 4} fontSize={11} fill="#0f172a" stroke="#fff" strokeWidth={3} paintOrder="stroke">{mark.label}</text>
        )}
      </g>
    );
  }
  if (g.type === "LineString" || g.type === "MultiLineString") {
    const lines = g.type === "LineString" ? [g.coordinates] : g.coordinates;
    return (
      <path d={lines.map((l) => path(l, at, false)).join(" ")} fill="none" stroke={mark.colour} strokeWidth={mark.size ?? 1.6}
        strokeDasharray={mark.dashed ? "5 4" : undefined} strokeOpacity={0.85}>
        <title>{mark.title}</title>
      </path>
    );
  }
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  return (
    <path d={polys.flatMap((rings) => rings.map((r) => path(r, at, true))).join(" ")} fill={mark.colour}
      fillOpacity={mark.fill ?? 0.25} stroke={mark.colour} strokeWidth={1} fillRule="evenodd">
      <title>{mark.title}</title>
    </path>
  );
}

export default function GeoMap({ marks, legend, caption, onPick }: {
  marks: GeoMark[];
  /** A pickable mark clicked (or Enter on it): its id. */
  onPick?: (id: string) => void;
  /** One row per layer: its name, colour and what it means. */
  legend?: { layer: string; colour: string; text: string }[];
  caption?: string;
}) {
  const { options: basemaps, chosen, choose } = useSiteBasemap();
  const layers = useMemo(() => [...new Set(marks.map((m) => m.layer))], [marks]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [labels, setLabels] = useState(marks.length <= 150);
  const shown = marks.filter((m) => !hidden.has(m.layer));
  const frame = frameOf(marks, chosen);
  if (!frame) return <p className="text-sm text-slate-600">Nothing here has a place on the map.</p>;
  // Areas first, then lines, then points on top: small marks are never hidden under big ones.
  const order = (m: GeoMark) => (m.geometry.type === "Point" ? 2 : m.geometry.type.includes("Line") ? 1 : 0);
  const sorted = [...shown].sort((a, b) => order(a) - order(b));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
        {basemaps.length > 0 && (
          <label className="flex items-center gap-1">Background
            <select className="rounded border border-slate-300 px-1 py-0.5 text-xs" value={chosen?.id ?? "none"}
              onChange={(e) => choose(e.target.value)}>
              <option value="none">none</option>
              {basemaps.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </label>
        )}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} /> Names
        </label>
        {layers.length > 1 && layers.map((layer) => {
          const entry = legend?.find((l) => l.layer === layer);
          return (
            <label key={layer} className="flex items-center gap-1">
              <input type="checkbox" checked={!hidden.has(layer)}
                onChange={(e) => setHidden((now) => { const next = new Set(now); if (e.target.checked) next.delete(layer); else next.add(layer); return next; })} />
              {entry && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: entry.colour }} aria-hidden />}
              {entry?.text ?? layer}
            </label>
          );
        })}
      </div>
      <div className="relative w-full max-w-3xl overflow-hidden rounded border border-slate-200 bg-white" style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="absolute inset-0 h-full w-full" role="img" aria-label={caption ?? "Map"}>
          {chosen && frame.tiles.map((tile) => (
            <image key={`${tile.z}/${tile.x}/${tile.y}/${tile.left}`} href={tileUrl(chosen.url, tile)} x={tile.left} y={tile.top}
              width={tile.size + 0.5} height={tile.size + 0.5} opacity={0.85} />
          ))}
          {sorted.map((m) =>
            onPick && m.pickable ? (
              <g key={m.id} role="button" tabIndex={0} aria-label={`Open ${m.title}`} className="cursor-pointer"
                onClick={() => onPick(m.id)} onKeyDown={(e) => { if (e.key === "Enter") onPick(m.id); }}>
                <Mark mark={m} at={frame.at} showLabel={labels} />
              </g>
            ) : (
              <Mark key={m.id} mark={m} at={frame.at} showLabel={labels} />
            ))}
        </svg>
      </div>
      {legend && legend.length > 0 && layers.length <= 1 && (
        <ul className="flex flex-wrap gap-3 text-xs text-slate-600">
          {legend.map((l) => (
            <li key={l.layer} className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: l.colour }} aria-hidden />{l.text}
            </li>
          ))}
        </ul>
      )}
      {caption && <p className="text-xs text-slate-500">{caption}</p>}
    </div>
  );
}
