/**
 * A site's map: local metres drawn over imagery, with pan and zoom. The camp
 * editor and the map data viewer both draw on it.
 *
 * The view is a centre in local metres and metres per screen pixel. Tiles
 * are Web Mercator; each is placed by its corners, converted to local
 * metres (`lib/campGeo`), so the drawing and the imagery agree wherever the
 * camp's origin is. Children draw with `at`, metres to screen.
 *
 * Pointer events reach the caller in metres. A drag the caller does not
 * take (it returns false from `onDown`), a middle- or right-button drag,
 * or any drag with the space bar held pans; the wheel zooms about the
 * cursor.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useBasemaps } from "../../hooks/useBasemaps";
import type { Pt, Ring } from "../../api/camps";
import { toLocal, toLonLat } from "../../lib/campGeo";
import { tileUrl, type Basemap } from "../../lib/tiles";

export type MapView = { cx: number; cy: number; mpp: number };
export type At = (p: Pt) => [number, number];

/** Built in, for when the organization names no tile server: a browser with internet reaches them. */
export const BUILTIN_BASEMAPS: Basemap[] = [
  {
    id: "builtin-satellite",
    name: "Satellite (Esri World Imagery)",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    minzoom: 0,
    maxzoom: 19,
  },
  {
    id: "builtin-streets",
    name: "Streets (OpenStreetMap)",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap contributors",
    minzoom: 0,
    maxzoom: 19,
  },
];

const EARTH = 156543.03392804097; // metres per pixel at zoom 0 on the equator, 256-pixel tiles
const MAX_TILES = 80;

export function fitRings(rings: Ring[], width: number, height: number, pad = 40): MapView | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const r of rings)
    for (const [x, y] of r) {
      minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    }
  if (!Number.isFinite(minX)) return null;
  const mpp = Math.max((maxX - minX) / Math.max(width - 2 * pad, 50), (maxY - minY) / Math.max(height - 2 * pad, 50), 0.01);
  return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, mpp };
}

function tileLonLat(px: number, py: number, z: number): Pt {
  const size = 256 * 2 ** z;
  const lon = (px / size) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * py) / size))) * 180) / Math.PI;
  return [lon, lat];
}

function worldPixel(lon: number, lat: number, z: number): Pt {
  const size = 256 * 2 ** z;
  const s = Math.sin((Math.max(-85.0511, Math.min(85.0511, lat)) * Math.PI) / 180);
  return [((lon + 180) / 360) * size, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size];
}

function niceLength(metres: number): number {
  const p = 10 ** Math.floor(Math.log10(metres));
  for (const m of [5, 2, 1]) if (m * p <= metres) return m * p;
  return p;
}

/** The backgrounds a map offers: the organization's tile index first, then the built-in ones; the choice is remembered. */
export function useSiteBasemap(storageKey = "solver_site_basemap"): { options: Basemap[]; chosen: Basemap | null; choose: (id: string) => void } {
  const org = useBasemaps();
  const options = [...org.basemaps, ...BUILTIN_BASEMAPS];
  const [choice, setChoice] = useState<string | null>(() => {
    try { return localStorage.getItem(storageKey); } catch { return null; }
  });
  const chosen = choice === "none" ? null : options.find((b) => b.id === choice) ?? options[0] ?? null;
  return {
    options, chosen,
    choose: (id) => {
      setChoice(id);
      try { localStorage.setItem(storageKey, id); } catch { /* this page only */ }
    },
  };
}

type Props = {
  origin: Pt;
  /** How far the drawing's +y axis is turned clockwise from north (a camp's own grid). */
  bearing?: number;
  view: MapView;
  onView: (view: MapView) => void;
  basemap: Basemap | null;
  height: number | string;
  cursor?: string;
  onDown?: (p: Pt, e: React.PointerEvent) => boolean | void;
  onMove?: (p: Pt, e: React.PointerEvent) => void;
  onUp?: (p: Pt, e: React.PointerEvent) => void;
  onDoubleClick?: (p: Pt, e: React.MouseEvent) => void;
  onSize?: (width: number, height: number) => void;
  children?: (at: At, mpp: number) => ReactNode;
  /** Drawn on a canvas under the SVG: for many features, where SVG would be thousands of nodes. */
  canvas?: (ctx: CanvasRenderingContext2D, at: At, mpp: number) => void;
  /** A click without a drag, in metres. */
  onClick?: (p: Pt, e: React.MouseEvent) => void;
  overlay?: ReactNode;
  label: string;
};

export default function CampMap({
  origin, bearing = 0, view, onView, basemap, height, cursor, onDown, onMove, onUp, onDoubleClick, onSize, children, canvas, onClick,
  overlay, label,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<[number, number]>([800, 560]);
  const [pointer, setPointer] = useState<Pt | null>(null);
  const pan = useRef<{ x: number; y: number; view: MapView } | null>(null);
  const space = useRef(false);
  const [failed, setFailed] = useState(0);
  const paper = useRef<HTMLCanvasElement>(null);
  const pressed = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const w = Math.max(200, Math.round(entry.contentRect.width));
      const h = Math.max(200, Math.round(entry.contentRect.height));
      setSize([w, h]);
      onSize?.(w, h);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [onSize]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.code === "Space" && !(e.target instanceof HTMLInputElement)) space.current = true; };
    const up = (e: KeyboardEvent) => { if (e.code === "Space") space.current = false; };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, []);

  const [w, h] = size;
  const at: At = useCallback(
    (p: Pt) => [(p[0] - view.cx) / view.mpp + w / 2, h / 2 - (p[1] - view.cy) / view.mpp],
    [view, w, h],
  );
  const fromScreen = useCallback(
    (sx: number, sy: number): Pt => [view.cx + (sx - w / 2) * view.mpp, view.cy - (sy - h / 2) * view.mpp],
    [view, w, h],
  );
  const local = (e: { clientX: number; clientY: number }): Pt => {
    const r = box.current!.getBoundingClientRect();
    return fromScreen(e.clientX - r.left, e.clientY - r.top);
  };

  // Wheel zoom about the cursor; not passive, so the page does not scroll.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      const factor = Math.exp(Math.max(-1, Math.min(1, e.deltaY / 300)));
      const mpp = Math.max(0.005, Math.min(50, view.mpp * factor));
      const p = fromScreen(sx, sy);
      onView({ mpp, cx: p[0] - (sx - w / 2) * mpp, cy: p[1] + (sy - h / 2) * mpp });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [view, w, h, fromScreen, onView]);

  const tiles = useMemo(() => {
    if (!basemap) return [];
    const lat = origin[1];
    const ideal = Math.log2((EARTH * Math.cos((lat * Math.PI) / 180)) / view.mpp);
    const z = Math.max(basemap.minzoom, Math.min(basemap.maxzoom, Math.ceil(ideal)));
    // The view's extent on the Earth: all four corners, the grid may be turned.
    const corners = [fromScreen(0, 0), fromScreen(w, 0), fromScreen(0, h), fromScreen(w, h)].map((p) => toLonLat(p, origin, bearing));
    const pix = corners.map((c) => worldPixel(c[0], c[1], z));
    const [x0, y0] = [Math.min(...pix.map((p) => p[0])), Math.min(...pix.map((p) => p[1]))];
    const [x1, y1] = [Math.max(...pix.map((p) => p[0])), Math.max(...pix.map((p) => p[1]))];
    const count = 2 ** z;
    const out: { key: string; href: string; x: number; y: number; w: number; h: number; angle: number }[] = [];
    for (let ty = Math.max(0, Math.floor(y0 / 256)); ty <= Math.min(count - 1, Math.floor(y1 / 256)); ty += 1)
      for (let tx = Math.floor(x0 / 256); tx <= Math.floor(x1 / 256); tx += 1) {
        if (out.length >= MAX_TILES) return out;
        const tl = at(toLocal(tileLonLat(tx * 256, ty * 256, z), origin, bearing));
        const tr = at(toLocal(tileLonLat((tx + 1) * 256, ty * 256, z), origin, bearing));
        const bl = at(toLocal(tileLonLat(tx * 256, (ty + 1) * 256, z), origin, bearing));
        const x = ((tx % count) + count) % count;
        out.push({
          key: `${z}/${tx}/${ty}`, href: tileUrl(basemap.url, { x, y: ty, z }), x: tl[0], y: tl[1],
          w: Math.hypot(tr[0] - tl[0], tr[1] - tl[1]), h: Math.hypot(bl[0] - tl[0], bl[1] - tl[1]),
          angle: (Math.atan2(tr[1] - tl[1], tr[0] - tl[0]) * 180) / Math.PI,
        });
      }
    return out;
  }, [basemap, origin, bearing, view, w, h, at, fromScreen]);

  useEffect(() => {
    const el = paper.current;
    if (!el || !canvas) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = w * ratio;
    el.height = h * ratio;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    canvas(ctx, at, view.mpp);
  }, [canvas, at, view.mpp, w, h]);

  const bar = niceLength(view.mpp * 120);
  const lonlat = pointer ? toLonLat(pointer, origin, bearing) : null;

  return (
    <div
      ref={box}
      className="relative select-none overflow-hidden rounded-lg border border-slate-300 bg-slate-100"
      style={{ height, cursor: pan.current ? "grabbing" : cursor ?? "default", touchAction: "none" }}
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={(e) => {
        (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
        pressed.current = { x: e.clientX, y: e.clientY };
        const p = local(e);
        const wantsPan = e.button === 1 || e.button === 2 || space.current;
        if (!wantsPan && e.button === 0 && onDown?.(p, e) !== false) return;
        pan.current = { x: e.clientX, y: e.clientY, view };
      }}
      onPointerMove={(e) => {
        const p = local(e);
        setPointer(p);
        if (pan.current) {
          const s = pan.current;
          onView({ ...s.view, cx: s.view.cx - (e.clientX - s.x) * s.view.mpp, cy: s.view.cy + (e.clientY - s.y) * s.view.mpp });
          return;
        }
        onMove?.(p, e);
      }}
      onPointerUp={(e) => {
        const start = pressed.current;
        pressed.current = null;
        if (start && onClick && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) onClick(local(e), e);
        if (pan.current) {
          pan.current = null;
          return;
        }
        onUp?.(local(e), e);
      }}
      onPointerLeave={() => setPointer(null)}
      onDoubleClick={(e) => onDoubleClick?.(local(e), e)}
      role="application"
      aria-label={label}
    >
      <svg width={w} height={h} className="absolute inset-0 block">
        {tiles.map((t) => (
          <image key={t.key} href={t.href} x={t.x} y={t.y} width={t.w + 0.5} height={t.h + 0.5} preserveAspectRatio="none"
            transform={Math.abs(t.angle) > 0.001 ? `rotate(${t.angle.toFixed(4)} ${t.x} ${t.y})` : undefined}
            onError={() => setFailed((n) => n + 1)} />
        ))}
      </svg>
      {canvas && <canvas ref={paper} className="pointer-events-none absolute inset-0" style={{ width: w, height: h }} />}
      {children && (
        <svg width={w} height={h} className="pointer-events-auto absolute inset-0 block">{children(at, view.mpp)}</svg>
      )}
      {overlay}
      <div className="pointer-events-none absolute bottom-2 left-2 flex items-end gap-3 text-[11px] text-slate-800">
        <div className="rounded bg-white/85 px-1.5 py-0.5 shadow-sm">
          <div className="h-1.5 border-x-2 border-b-2 border-slate-800" style={{ width: bar / view.mpp }} />
          <span>{bar >= 1000 ? `${bar / 1000} km` : `${bar} m`}</span>
        </div>
        {pointer && lonlat && (
          <div className="rounded bg-white/85 px-1.5 py-0.5 font-mono shadow-sm">
            x {pointer[0].toFixed(2)} m, y {pointer[1].toFixed(2)} m · {lonlat[1].toFixed(6)}, {lonlat[0].toFixed(6)}
          </div>
        )}
      </div>
      <div className="pointer-events-none absolute right-2 top-2 flex h-8 w-8 flex-col items-center justify-center rounded-full bg-white/85 text-[10px] font-bold text-slate-800 shadow-sm" aria-hidden
        style={bearing ? { transform: `rotate(${-bearing}deg)` } : undefined} title={bearing ? `North; the grid is turned ${bearing}°` : "North"}>
        <span>▲</span><span className="-mt-1">N</span>
      </div>
      {basemap && (
        <div className="pointer-events-none absolute bottom-2 right-2 max-w-[50%] truncate rounded bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-700">
          {failed > 0 && tiles.length > 0 ? "Imagery could not be loaded here · " : ""}{basemap.attribution}
        </div>
      )}
    </div>
  );
}
