/**
 * Shapes as a record stores them (GeoJSON, longitude then latitude), for drawing and editing on a map.
 */
import type { GeoGeometry } from "../components/map/GeoMap";

export type LonLat = [number, number];
export type DrawMode = "point" | "line" | "area";

/** Every position of a shape, flattened. */
export function positionsOf(g: GeoGeometry): LonLat[] {
  switch (g.type) {
    case "Point":
      return [g.coordinates as LonLat];
    case "LineString":
      return g.coordinates as LonLat[];
    case "MultiLineString":
      return g.coordinates.flat() as LonLat[];
    case "Polygon":
      return g.coordinates.flat() as LonLat[];
    case "MultiPolygon":
      return g.coordinates.flat(2) as LonLat[];
  }
}

/** A value that is a shape this app draws, or null. */
export function asGeometry(value: unknown): GeoGeometry | null {
  const g = value as { type?: unknown; coordinates?: unknown } | null;
  if (!g || typeof g !== "object" || !Array.isArray(g.coordinates)) return null;
  return ["Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"].includes(String(g.type)) ? (g as GeoGeometry) : null;
}

/** The middle of the shapes' extent: where a map of them opens. */
export function middleOf(shapes: GeoGeometry[]): LonLat | null {
  const all = shapes.flatMap(positionsOf);
  if (!all.length) return null;
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
}

/** What a draft drawn in `mode` becomes, or why it is not a shape yet. */
export function shapeOf(mode: DrawMode, points: LonLat[]): { geometry: GeoGeometry } | { problem: string } {
  const round = (p: LonLat): LonLat => [Number(p[0].toFixed(7)), Number(p[1].toFixed(7))];
  const pts = points.map(round);
  if (mode === "point") return pts.length ? { geometry: { type: "Point", coordinates: pts[pts.length - 1] } } : { problem: "Click where it is." };
  if (mode === "line") return pts.length >= 2 ? { geometry: { type: "LineString", coordinates: pts } } : { problem: "A line needs two points or more." };
  if (pts.length < 3) return { problem: "An area needs three corners or more." };
  return { geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } };
}

/** A shape in words: "a point at 30.0444, 31.2357", "an area of 5 corners". */
export function describeShape(g: GeoGeometry | null): string {
  if (!g) return "no place yet";
  if (g.type === "Point") return `a point at ${g.coordinates[1].toFixed(5)}, ${g.coordinates[0].toFixed(5)}`;
  if (g.type === "LineString") return `a line of ${g.coordinates.length} points`;
  if (g.type === "Polygon") return `an area of ${Math.max(0, g.coordinates[0].length - 1)} corners`;
  return `a ${g.type}`;
}
