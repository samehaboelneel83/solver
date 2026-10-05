/**
 * GIS features on a canvas: prepared once into local metres around an
 * origin (`lib/geo`), then drawn each frame with only what is in view,
 * and found again under the pointer.
 */
import type { GisFeature } from "../api/gis";
import { inside, toLocal, type Pt } from "./geo";

export type Prepared = {
  feature: GisFeature;
  key: number;
  layer: string;
  kind: string;
  /** point/text: one point; line: one path; polygon: rings */
  parts: Pt[][];
  box: [number, number, number, number];
};

export function prepare(features: GisFeature[], origin: Pt): Prepared[] {
  return features.map((f, key) => {
    const g = f.geometry;
    const parts: Pt[][] = g.type === "Point" ? [[toLocal(g.coordinates as Pt, origin)]]
      : g.type === "LineString" ? [(g.coordinates as Pt[]).map((p) => toLocal(p, origin))]
        : (g.coordinates as Pt[][]).map((ring) => ring.map((p) => toLocal(p, origin)));
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const part of parts)
      for (const [x, y] of part) {
        minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      }
    return { feature: f, key, layer: f.properties.layer, kind: f.properties.kind, parts, box: [minX, minY, maxX, maxY] };
  });
}

export function extentOf(items: Prepared[]): [number, number, number, number] | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of items) {
    minX = Math.min(minX, p.box[0]); minY = Math.min(minY, p.box[1]); maxX = Math.max(maxX, p.box[2]); maxY = Math.max(maxY, p.box[3]);
  }
  return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
}

export type DrawOptions = {
  visible: (layer: string) => boolean;
  colour: (item: Prepared) => string;
  selected?: number | null;
  labels?: boolean;
  /** The view in metres: what lies outside it is not drawn. */
  view: [number, number, number, number];
};

function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export function draw(ctx: CanvasRenderingContext2D, items: Prepared[], at: (p: Pt) => [number, number], mpp: number, o: DrawOptions) {
  const [vx0, vy0, vx1, vy1] = o.view;
  const order = { polygon: 0, line: 1, point: 2, text: 3 } as Record<string, number>;
  const shown = items.filter((p) => o.visible(p.layer) && p.box[2] >= vx0 && p.box[0] <= vx1 && p.box[3] >= vy0 && p.box[1] <= vy1);
  shown.sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (const p of shown) {
    const colour = o.colour(p);
    const chosen = o.selected === p.key;
    if (p.kind === "polygon") {
      ctx.beginPath();
      for (const ring of p.parts) {
        ring.forEach((q, i) => { const [x, y] = at(q); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.closePath();
      }
      ctx.fillStyle = withAlpha(colour, p.feature.properties.solid ? 0.55 : 0.22);
      ctx.fill("evenodd");
      ctx.strokeStyle = chosen ? "#2563eb" : colour;
      ctx.lineWidth = chosen ? 3 : 1.2;
      ctx.stroke();
    } else if (p.kind === "line") {
      ctx.beginPath();
      p.parts[0].forEach((q, i) => { const [x, y] = at(q); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      ctx.strokeStyle = chosen ? "#2563eb" : colour;
      ctx.lineWidth = chosen ? 3.5 : 1.5;
      ctx.stroke();
    } else if (p.kind === "point") {
      const [x, y] = at(p.parts[0][0]);
      ctx.beginPath();
      ctx.arc(x, y, chosen ? 5.5 : p.feature.properties.block_reference ? 3.5 : 3, 0, Math.PI * 2);
      ctx.fillStyle = chosen ? "#2563eb" : colour;
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.stroke();
    } else if (p.kind === "text" && o.labels !== false) {
      const words = String(p.feature.properties.text ?? "");
      const height = Number(p.feature.properties.height ?? 0);
      const size = height > 0 ? height / mpp : 11;
      if (size < 5 || !words) continue;
      const [x, y] = at(p.parts[0][0]);
      ctx.save();
      ctx.translate(x, y);
      const rotation = Number(p.feature.properties.rotation ?? 0);
      if (rotation) ctx.rotate((-rotation * Math.PI) / 180);
      ctx.font = `${Math.min(48, size).toFixed(1)}px system-ui, sans-serif`;
      ctx.textBaseline = "alphabetic";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      const lines = words.split("\n");
      lines.forEach((line, i) => {
        ctx.strokeText(line, 0, i * Math.min(48, size) * 1.2);
        ctx.fillStyle = chosen ? "#2563eb" : colour;
        ctx.fillText(line, 0, i * Math.min(48, size) * 1.2);
      });
      ctx.restore();
    }
  }
  return shown.length;
}

function segmentDistance(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** The feature under `p` (metres): a point or text, then a line, then the smallest polygon around it. */
export function hit(items: Prepared[], p: Pt, mpp: number, visible: (layer: string) => boolean): Prepared | null {
  const reach = 6 * mpp;
  let best: { item: Prepared; score: number } | null = null;
  for (const item of items) {
    if (!visible(item.layer)) continue;
    const [x0, y0, x1, y1] = item.box;
    if (p[0] < x0 - reach || p[0] > x1 + reach || p[1] < y0 - reach || p[1] > y1 + reach) continue;
    let score = Infinity;
    if (item.kind === "point" || item.kind === "text") {
      const d = Math.hypot(p[0] - item.parts[0][0][0], p[1] - item.parts[0][0][1]);
      if (d <= reach * (item.kind === "text" ? 2 : 1)) score = d / reach;
    } else if (item.kind === "line") {
      const path = item.parts[0];
      for (let i = 1; i < path.length; i += 1) {
        const d = segmentDistance(p, path[i - 1], path[i]);
        if (d <= reach) score = Math.min(score, 1 + d / reach);
      }
    } else if (inside(p, item.parts[0]) && !item.parts.slice(1).some((hole) => inside(p, hole))) {
      score = 3 + Math.log10(1 + (x1 - x0) * (y1 - y0));
    }
    if (score < (best?.score ?? Infinity)) best = { item, score };
  }
  return best?.item ?? null;
}
