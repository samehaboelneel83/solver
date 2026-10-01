/**
 * Geometry for the camp editor: local metres (x east, y north) around an
 * origin longitude and latitude, and the drawing rules a camp follows.
 *
 * Local metres to the map: metres per degree on the WGS84 ellipsoid at the
 * origin's latitude. Over a camp (hundreds of metres) this agrees with the
 * engine's azimuthal equidistant projection to well under a centimetre.
 */
import type { CampProblem, Pt, Ring } from "../api/camps";

const RAD = Math.PI / 180;

/** Metres in one degree of latitude and of longitude at `lat`. */
export function metresPerDegree(lat: number): [number, number] {
  const φ = lat * RAD;
  const perLat = 111132.92 - 559.82 * Math.cos(2 * φ) + 1.175 * Math.cos(4 * φ) - 0.0023 * Math.cos(6 * φ);
  const perLon = 111412.84 * Math.cos(φ) - 93.5 * Math.cos(3 * φ) + 0.118 * Math.cos(5 * φ);
  return [perLat, perLon];
}

/** Local metres to longitude and latitude. `bearing`: how far the local +y axis is turned clockwise from north. */
export function toLonLat(p: Pt, origin: Pt, bearing = 0): Pt {
  const [perLat, perLon] = metresPerDegree(origin[1]);
  const c = Math.cos(bearing * RAD), s = Math.sin(bearing * RAD);
  const east = p[0] * c + p[1] * s, north = -p[0] * s + p[1] * c;
  return [origin[0] + east / perLon, origin[1] + north / perLat];
}

export function toLocal(lonlat: Pt, origin: Pt, bearing = 0): Pt {
  const [perLat, perLon] = metresPerDegree(origin[1]);
  const east = (lonlat[0] - origin[0]) * perLon, north = (lonlat[1] - origin[1]) * perLat;
  const c = Math.cos(bearing * RAD), s = Math.sin(bearing * RAD);
  return [east * c - north * s, east * s + north * c];
}

export const round = (v: number, step = 0.001) => Math.round(v / step) * step;
export const roundPt = (p: Pt, step = 0.001): Pt => [Number(round(p[0], step).toFixed(4)), Number(round(p[1], step).toFixed(4))];

export function snap(p: Pt, step: number): Pt {
  return step > 0 ? roundPt([Math.round(p[0] / step) * step, Math.round(p[1] / step) * step]) : roundPt(p);
}

/** `p` moved to the nearest horizontal or vertical line through `from`. */
export function orthogonal(from: Pt, p: Pt): Pt {
  return Math.abs(p[0] - from[0]) >= Math.abs(p[1] - from[1]) ? [p[0], from[1]] : [from[0], p[1]];
}

export function area(ring: Ring): number {
  let s = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

export function centroid(ring: Ring): Pt {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    const f = x1 * y2 - x2 * y1;
    a += f;
    cx += (x1 + x2) * f;
    cy += (y1 + y2) * f;
  }
  if (Math.abs(a) < 1e-9) {
    const n = Math.max(ring.length, 1);
    return [ring.reduce((s, p) => s + p[0], 0) / n, ring.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

export function inside(p: Pt, ring: Ring): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

export function bounds(rings: Ring[]): [number, number, number, number] | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const ring of rings)
    for (const [x, y] of ring) {
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
}

export function rectangle(a: Pt, b: Pt): Ring {
  const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
  const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

/** A circle as a polygon that encloses it: corners just outside, so a bed kept off the polygon is off the circle. */
export function circle(centre: Pt, radius: number, corners = 32): Ring {
  const out = radius / Math.cos(Math.PI / corners);
  return Array.from({ length: corners }, (_, k) => roundPt([
    centre[0] + out * Math.cos((2 * Math.PI * k) / corners),
    centre[1] + out * Math.sin((2 * Math.PI * k) / corners),
  ], 0.01));
}

function distanceToSegment(p: Pt, a: Pt, b: Pt): { d: number; t: number } {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  const q: Pt = [a[0] + t * dx, a[1] + t * dy];
  return { d: Math.hypot(p[0] - q[0], p[1] - q[1]), t };
}

/** The boundary's horizontal and vertical walls, as [start, end] pairs. */
export function axisWalls(boundary: Ring): [Pt, Pt][] {
  const walls: [Pt, Pt][] = [];
  for (let i = 0; i < boundary.length; i += 1) {
    const a = boundary[i], b = boundary[(i + 1) % boundary.length];
    if ((Math.abs(a[0] - b[0]) < 1e-9 || Math.abs(a[1] - b[1]) < 1e-9) && (a[0] !== b[0] || a[1] !== b[1])) walls.push([a, b]);
  }
  return walls;
}

export function nearestWall(p: Pt, boundary: Ring, within = Infinity): { wall: [Pt, Pt]; d: number } | null {
  let best: { wall: [Pt, Pt]; d: number } | null = null;
  for (const wall of axisWalls(boundary)) {
    const { d } = distanceToSegment(p, wall[0], wall[1]);
    if (d <= within && (!best || d < best.d)) best = { wall, d };
  }
  return best;
}

/** A point slid along a wall: its projection, kept on the wall. */
export function onWall(p: Pt, wall: [Pt, Pt]): Pt {
  const [a, b] = wall;
  if (Math.abs(a[1] - b[1]) < 1e-9) return [Math.max(Math.min(a[0], b[0]), Math.min(Math.max(a[0], b[0]), p[0])), a[1]];
  return [a[0], Math.max(Math.min(a[1], b[1]), Math.min(Math.max(a[1], b[1]), p[1]))];
}

/** A door `width` wide centred where `p` meets the nearest wall, kept on that wall; null if the wall is shorter. */
export function doorAt(p: Pt, boundary: Ring, width: number, step: number, within = Infinity): [Pt, Pt] | null {
  const near = nearestWall(p, boundary, within);
  if (!near) return null;
  const [a, b] = near.wall;
  const horizontal = Math.abs(a[1] - b[1]) < 1e-9;
  const lo = horizontal ? Math.min(a[0], b[0]) : Math.min(a[1], b[1]);
  const hi = horizontal ? Math.max(a[0], b[0]) : Math.max(a[1], b[1]);
  if (hi - lo < width) return null;
  let mid = horizontal ? p[0] : p[1];
  if (step > 0) mid = Math.round(mid / step) * step;
  const start = Math.max(lo, Math.min(hi - width, mid - width / 2));
  const pts: [Pt, Pt] = horizontal
    ? [roundPt([start, a[1]]), roundPt([start + width, a[1]])]
    : [roundPt([a[0], start]), roundPt([a[0], start + width])];
  return pts;
}

export function length(a: Pt, b: Pt): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** A name not yet used: `base1`, `base2`... */
export function freshName(base: string, taken: string[]): string {
  const used = new Set(taken);
  for (let k = 1; ; k += 1) if (!used.has(`${base}${k}`)) return `${base}${k}`;
}

/** Every ring of the camp, for fitting the view. */
export function campRings(problem: CampProblem): Ring[] {
  return [
    problem.boundary,
    ...problem.obstacles.map((s) => s.ring),
    ...problem.prohibited.map((s) => s.ring),
    ...problem.placement_zones.map((s) => s.ring),
  ].filter((r) => r.length > 0);
}

/** "30.1, 31.6" or "31.6 30.1"-style text as a longitude-latitude pair, or null. Latitude first is the
 * common way to write it (and what a map app copies), so two numbers are read lat, lon. */
export function parseLatLon(text: string): Pt | null {
  const nums = text.match(/-?\d+(?:\.\d+)?/g);
  if (!nums || nums.length !== 2) return null;
  const [lat, lon] = nums.map(Number);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return [lon, lat];
}
