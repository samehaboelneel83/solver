/**
 * A GeoJSON geometry drawn small, north up, fitted to its box -- never raw
 * JSON on a page (spatial spec §5). Longitude is shortened by the cosine of
 * the latitude, so a square on the ground looks square.
 */
type Position = number[];
type Geometry = { type?: unknown; coordinates?: unknown };

function rings(g: Geometry): Position[][] {
  try {
    if (g.type === "Polygon") return g.coordinates as Position[][];
    if (g.type === "MultiPolygon") return (g.coordinates as Position[][][]).flat();
    if (g.type === "Point") return [[g.coordinates as Position]];
  } catch {
    // Not the shape its type says: nothing to draw.
  }
  return [];
}

export default function GeometryPreview({ geometry, size = 96 }: { geometry: unknown; size?: number }) {
  const g = (geometry && typeof geometry === "object" ? geometry : {}) as Geometry;
  const all = rings(g).filter(Array.isArray);
  const points = all.flat().filter((p) => Array.isArray(p) && p.length >= 2 && p.every((n) => typeof n === "number"));
  if (points.length === 0) return <span className="text-xs text-slate-500">No shape to draw</span>;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180) || 1;
  const span = Math.max((maxX - minX) * k, maxY - minY) || 1;
  const pad = 4;
  const x = (v: number) => pad + (((v - minX) * k) / span) * (size - 2 * pad);
  const y = (v: number) => size - pad - ((v - minY) / span) * (size - 2 * pad);
  const d = all
    .map((ring) => ring.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ") + " Z")
    .join(" ");
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`${String(g.type)}, ${points.length} positions`}
      className="rounded border border-slate-200 bg-slate-50"
    >
      {g.type === "Point" ? (
        <circle cx={x(points[0][0])} cy={y(points[0][1])} r={3} className="fill-blue-600" />
      ) : (
        <path d={d} className="fill-blue-100 stroke-blue-700" strokeWidth={1} fillRule="evenodd" />
      )}
    </svg>
  );
}
