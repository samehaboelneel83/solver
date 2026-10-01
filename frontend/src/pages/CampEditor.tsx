/**
 * One camp: drawn on the map, every value set beside it, laid out by the
 * worker and shown on the map (camp layout engine).
 *
 * **Draw.** The toolbar's tools draw the camp boundary, doors (a click on a
 * horizontal or vertical wall), closed areas, no-bed areas and bed zones,
 * as polygons, rectangles or circles, over satellite or street imagery.
 * Select a shape to drag its corners, slide a door along its wall, move it,
 * or type its numbers in the panel. The server checks the drawing as it
 * changes (`POST /camps/check`) and the door zones it implies are drawn.
 *
 * **Layout.** A solve runs in the worker; its progress shows here, and the
 * answer is drawn on the same map (`CampResult`).
 *
 * Undo and redo keep the last 100 changes; nothing is saved until Save
 * (or a solve, which saves first).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import {
  Circle as CircleIcon, DoorOpen, Download, FileUp, Hexagon, Layers, Map as MapIcon, Maximize2, MousePointer2, Move,
  Pentagon, Play, Redo2, Save, Square, Undo2,
} from "lucide-react";
import { formatApiError } from "../api/errors";
import {
  cancelCampSolve, checkCamp, downloadFrom, importCampFile, saveCamp, solveCamp, useCamp, useCampSolve,
  type CampCheck, type CampDoor, type CampDoorZone, type CampOptions, type CampPlan, type CampProblem, type CampShape,
  type Pt, type Ring,
} from "../api/camps";
import { useQueryClient } from "@tanstack/react-query";
import CampMap, { fitRings, useSiteBasemap, type At, type MapView } from "../components/map/SiteMap";
import { BedTypesPanel, CoordTable, DoorPanel, SettingsPanel, ShapePanel } from "../components/camp/CampPanels";
import { ResultLayers, ResultLegend, ResultPanel, type ColourBy } from "../components/camp/CampResult";
import LoadFailure from "../components/LoadFailure";
import Skeleton from "../components/Skeleton";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import {
  area, campRings, centroid, circle, doorAt, freshName, inside, length, nearestWall, onWall, orthogonal, rectangle,
  roundPt, snap, toLonLat,
} from "../lib/campGeo";

type ShapeKind = "obstacles" | "prohibited" | "placement_zones";
type Selection = { kind: "boundary" } | { kind: "door"; id: string } | { kind: ShapeKind; id: string };
type Tool = "select" | "boundary" | "door" | "obstacles" | "prohibited" | "placement_zones" | "place";
type Form = "polygon" | "rectangle" | "circle";
type Drag =
  | { type: "vertex"; sel: Selection; index: number }
  | { type: "move"; sel: Selection; start: Pt; ring: Ring }
  | { type: "door-end"; id: string; end: "a" | "b"; wall: [Pt, Pt] }
  | { type: "door-move"; id: string; start: Pt; a: Pt; b: Pt; wall: [Pt, Pt] }
  | { type: "place"; x: number; y: number; origin: Pt; view: MapView }
  | { type: "rect"; start: Pt }
  | { type: "circle"; start: Pt };

const KIND_LABEL: Record<ShapeKind, string> = { obstacles: "Closed area", prohibited: "No-beds area", placement_zones: "Bed zone" };
const KIND_BASE: Record<ShapeKind, string> = { obstacles: "closed-", prohibited: "no-beds-", placement_zones: "zone-" };
const FAULT_PREFIX: Record<ShapeKind, string> = { obstacles: "obstacle", prohibited: "no-beds area", placement_zones: "zone" };
const HANDLE_PX = 9;
const CAMP_BASEMAP_KEY = "solver_camp_basemap";
const SNAPS = [0, 0.1, 0.25, 0.5, 1];

const STYLE = {
  boundary: { fill: "rgba(255,255,255,0.35)", stroke: "#0f172a" },
  obstacles: { fill: "rgba(71,85,105,0.85)", stroke: "#1e293b" },
  prohibited: { fill: "url(#camp-hatch)", stroke: "#b91c1c" },
  placement_zones: { fill: "rgba(147,51,234,0.12)", stroke: "#7e22ce" },
  door: "#059669",
  zone: { fill: "rgba(245,158,11,0.28)", stroke: "#b45309" },
};

function ringPath(at: At, ring: Ring, close = true): string {
  if (!ring.length) return "";
  return ring.map((p, i) => `${i ? "L" : "M"}${at(p)[0].toFixed(1)},${at(p)[1].toFixed(1)}`).join("") + (close ? "Z" : "");
}

function distToSeg(p: [number, number], a: [number, number], b: [number, number]): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

function sameSel(a: Selection | null, b: Selection | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  return a.kind === "boundary" || (a as { id: string }).id === (b as { id: string }).id;
}

/** An old camp address (`/domains/:id/camps/:campId`): camps are under Map data now. */
export function CampRedirect() {
  const { domainId, campId } = useParams();
  return <Navigate to={`/domains/${domainId}/map-data/camps/${campId}`} replace />;
}

export default function CampEditor() {
  const { campId } = useParams();
  const id = Number(campId);
  const plan = useCamp(Number.isInteger(id) && id > 0 ? id : null);
  const { domainId } = useDomain();
  useDocumentTitle(plan.data?.name ?? "Camp");
  if (plan.isLoading) return <Skeleton rows={8} />;
  if (plan.isError || !plan.data)
    return <LoadFailure subject="This camp" error={plan.error} retry={() => void plan.refetch()}
      back={domainId ? { label: "All camps", to: `/domains/${domainId}/map-data/camps` } : undefined} />;
  return <CampWorkspace key={plan.data.id} plan={plan.data} />;
}

function CampWorkspace({ plan }: { plan: CampPlan }) {
  const client = useQueryClient();
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const canSolve = can("run.submit");
  const [problem, setProblemState] = useState<CampProblem>(plan.problem);
  const [name, setName] = useState(plan.name);
  const [options, setOptions] = useState<CampOptions>(plan.options);
  const [saved, setSaved] = useState(() => JSON.stringify([plan.problem, plan.name, plan.options]));
  const [updatedAt, setUpdatedAt] = useState(plan.updated_at);
  const past = useRef<CampProblem[]>([]);
  const future = useRef<CampProblem[]>([]);
  const [, bump] = useState(0);
  const [tool, setTool] = useState<Tool>("select");
  const [form, setForm] = useState<Form>("polygon");
  const [snapStep, setSnapStep] = useState(0.5);
  const [sel, setSel] = useState<Selection | null>(null);
  const [draft, setDraft] = useState<Ring>([]);
  const [hover, setHover] = useState<Pt | null>(null);
  const drag = useRef<Drag | null>(null);
  const [dragShape, setDragShape] = useState<Drag | null>(null);
  const [view, setView] = useState<MapView>({ cx: 15, cy: 10, mpp: 0.1 });
  const size = useRef<[number, number]>([800, 600]);
  const fitted = useRef(false);
  const [check, setCheck] = useState<CampCheck>(plan.check);
  const [tab, setTab] = useState<"shapes" | "beds" | "settings" | "solve">("shapes");
  const [mode, setMode] = useState<"draw" | "layout">(plan.solves[0]?.status === "done" ? "layout" : "draw");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [solveId, setSolveId] = useState<number | null>(plan.solves[0]?.id ?? null);
  const solve = useCampSolve(solveId);
  const [colourBy, setColourBy] = useState<ColourBy>("type");
  const [hoverBed, setHoverBed] = useState<string | null>(null);
  const [layers, setLayers] = useState({ zones: true, labels: true, paths: false });
  const basemap = useSiteBasemap(CAMP_BASEMAP_KEY);
  const importer = useRef<HTMLInputElement>(null);
  const [importUnits, setImportUnits] = useState("");

  const dirty = JSON.stringify([problem, name, options]) !== saved;

  const setProblem = useCallback((next: CampProblem | ((p: CampProblem) => CampProblem), record = true) => {
    setProblemState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      if (record && value !== prev) {
        past.current = [...past.current.slice(-99), prev];
        future.current = [];
        bump((n) => n + 1);
      }
      return value;
    });
  }, []);
  const undo = useCallback(() => {
    const prev = past.current.pop();
    if (!prev) return;
    setProblemState((cur) => { future.current.push(cur); return prev; });
    bump((n) => n + 1);
  }, []);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (!next) return;
    setProblemState((cur) => { past.current.push(cur); return next; });
    bump((n) => n + 1);
  }, []);

  // Fit the camp once the map knows its size.
  const fit = useCallback(() => {
    const v = fitRings(campRings(problem), size.current[0], size.current[1]);
    if (v) setView(v);
  }, [problem]);
  const onSize = useCallback((w: number, h: number) => {
    size.current = [w, h];
    if (!fitted.current) {
      fitted.current = true;
      const v = fitRings(campRings(plan.problem), w, h);
      if (v) setView(v);
    }
  }, [plan.problem]);

  // The server's check, a moment after the drawing stops changing.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      checkCamp(problem).then(setCheck).catch(() => undefined);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [problem]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useCallback(async (): Promise<boolean> => {
    setBusy("Saving…");
    setMessage(null);
    try {
      const out = await saveCamp(plan.id, { name, problem: { ...problem, name }, options, updated_at: updatedAt });
      setProblemState(out.problem);
      setName(out.name);
      setOptions(out.options);
      setSaved(JSON.stringify([out.problem, out.name, out.options]));
      setUpdatedAt(out.updated_at);
      setCheck(out.check);
      void client.invalidateQueries({ queryKey: ["camps", "list"] });
      return true;
    } catch (e) {
      setMessage(formatApiError(e));
      return false;
    } finally {
      setBusy(null);
    }
  }, [plan.id, name, problem, options, updatedAt, client]);

  const startSolve = async () => {
    if (dirty && !(await save())) return;
    setBusy("Asking the worker…");
    setMessage(null);
    try {
      const s = await solveCamp(plan.id, { solver: options.solver, beds_seconds: options.beds_seconds, seconds: options.seconds });
      setSolveId(s.id);
      setTab("solve");
      void client.invalidateQueries({ queryKey: ["camps", "solve", s.id] });
    } catch (e) {
      setMessage(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    if (solve.data?.status === "done" && solve.data.result) setMode((m) => (m === "draw" && tab === "solve" ? "layout" : m));
  }, [solve.data?.status, solve.data?.result, tab]);

  // -- editing helpers ------------------------------------------------------------------------
  const zoneOf = (door: string): CampDoorZone => problem.zones.find((z) => z.door === door) ?? { door, area_per_bed: 0.25 };
  const ringOf = (s: Selection, p: CampProblem = problem): Ring | null => {
    if (s.kind === "boundary") return p.boundary;
    if (s.kind === "door") return null;
    return p[s.kind].find((x) => x.id === s.id)?.ring ?? null;
  };
  const setRing = (s: Selection, ring: Ring, record = true) => {
    setProblem((p) => {
      if (s.kind === "boundary") return { ...p, boundary: ring };
      if (s.kind === "door") return p;
      return { ...p, [s.kind]: p[s.kind].map((x) => (x.id === s.id ? { ...x, ring } : x)) };
    }, record);
  };
  const setDoor = (door: CampDoor, record = true, oldId = door.id) =>
    setProblem((p) => ({ ...p, doors: p.doors.map((d) => (d.id === oldId ? door : d)) }), record);
  const remove = (s: Selection) => {
    if (s.kind === "boundary") return;
    setProblem((p) => s.kind === "door"
      ? { ...p, doors: p.doors.filter((d) => d.id !== s.id), zones: p.zones.filter((z) => z.door !== s.id) }
      : {
          ...p, [s.kind]: p[s.kind].filter((x) => x.id !== s.id),
          bed_types: s.kind === "placement_zones" ? p.bed_types.map((b) => (b.zone === s.id ? { ...b, zone: null } : b)) : p.bed_types,
        });
    setSel(null);
  };

  const finishRing = (ring: Ring) => {
    const clean = ring.filter((p, i) => i === 0 || p[0] !== ring[i - 1][0] || p[1] !== ring[i - 1][1]);
    if (clean.length > 1 && clean[0][0] === clean[clean.length - 1][0] && clean[0][1] === clean[clean.length - 1][1]) clean.pop();
    setDraft([]);
    if (clean.length < 3 || area(clean) < 0.01) {
      setMessage("A shape needs at least three corners that enclose some area.");
      return;
    }
    if (tool === "boundary") {
      setProblem((p) => ({ ...p, boundary: clean }));
      setSel({ kind: "boundary" });
      setMessage("The camp boundary is drawn. Doors not on its walls are listed in the checks.");
      setTool("select");
      return;
    }
    if (tool === "obstacles" || tool === "prohibited" || tool === "placement_zones") {
      const kind = tool;
      const newId = freshName(KIND_BASE[kind], problem[kind].map((s) => s.id));
      const shape: CampShape = kind === "obstacles" ? { id: newId, ring: clean, kind: "closed" } : { id: newId, ring: clean };
      setProblem((p) => ({ ...p, [kind]: [...p[kind], shape] }));
      setSel({ kind, id: newId });
      setMessage(null);
    }
  };

  // -- hit testing ---------------------------------------------------------------------------
  const hit = (p: Pt, atFn: At): Selection | null => {
    const s = atFn(p);
    for (const d of problem.doors) if (distToSeg(s, atFn(d.a), atFn(d.b)) <= HANDLE_PX) return { kind: "door", id: d.id };
    for (const kind of ["obstacles", "prohibited", "placement_zones"] as ShapeKind[])
      for (const shape of [...problem[kind]].reverse()) if (inside(p, shape.ring)) return { kind, id: shape.id };
    const b = problem.boundary;
    for (let i = 0; i < b.length; i += 1) if (distToSeg(s, atFn(b[i]), atFn(b[(i + 1) % b.length])) <= HANDLE_PX) return { kind: "boundary" };
    if (b.length >= 3 && inside(p, b)) return { kind: "boundary" };
    return null;
  };

  const atRef = useRef<At>((p) => [p[0], p[1]]);

  const onDown = (raw: Pt, e: React.PointerEvent): boolean => {
    if (mode !== "draw" || !canEdit) return false;
    const at = atRef.current;
    const p = e.altKey ? roundPt(raw) : snap(raw, snapStep);
    setMessage(null);
    if (tool === "place") {
      drag.current = { type: "place", x: e.clientX, y: e.clientY, origin: problem.origin_lonlat, view };
      past.current = [...past.current.slice(-99), problem];
      future.current = [];
      return true;
    }
    if (tool === "door") {
      const width = 2;
      const pts = doorAt(raw, problem.boundary, width, snapStep, 25 * view.mpp + 0.5);
      if (!pts) {
        setMessage("Click on a horizontal or vertical wall of the camp, at least 2 m long, to put a door there.");
        return true;
      }
      const newId = freshName("D", problem.doors.map((d) => d.id));
      setProblem((q) => ({ ...q, doors: [...q.doors, { id: newId, a: pts[0], b: pts[1], capacity: null }],
        zones: [...q.zones, { door: newId, area_per_bed: 0.25 }] }));
      setSel({ kind: "door", id: newId });
      setTab("shapes");
      return true;
    }
    if (tool !== "select") {
      if (form === "rectangle" || (form === "circle" && tool === "obstacles")) {
        drag.current = { type: form === "rectangle" ? "rect" : "circle", start: p };
        setDragShape(drag.current);
        return true;
      }
      // Polygon: a click adds a corner; on the first corner it closes.
      const last = draft[draft.length - 1];
      const point = e.shiftKey && last ? orthogonal(last, p) : p;
      if (draft.length >= 3) {
        const first = at(draft[0]), here = at(point);
        if (Math.hypot(first[0] - here[0], first[1] - here[1]) <= HANDLE_PX + 2) {
          finishRing(draft);
          return true;
        }
      }
      setDraft([...draft, point]);
      return true;
    }
    // Select: handles of the selected shape first.
    const s = at(raw);
    if (sel?.kind === "door") {
      const door = problem.doors.find((d) => d.id === sel.id);
      if (door) {
        const wall = nearestWall([(door.a[0] + door.b[0]) / 2, (door.a[1] + door.b[1]) / 2], problem.boundary, 0.05);
        for (const end of ["a", "b"] as const) {
          const h = at(door[end]);
          if (Math.hypot(h[0] - s[0], h[1] - s[1]) <= HANDLE_PX && wall) {
            past.current = [...past.current.slice(-99), problem];
            future.current = [];
            drag.current = { type: "door-end", id: door.id, end, wall: wall.wall };
            return true;
          }
        }
      }
    }
    const ring = sel ? ringOf(sel) : null;
    if (sel && ring) {
      for (let i = 0; i < ring.length; i += 1) {
        const h = at(ring[i]);
        if (Math.hypot(h[0] - s[0], h[1] - s[1]) <= HANDLE_PX) {
          if (e.altKey && ring.length > 3) {
            setRing(sel, ring.filter((_, k) => k !== i));
            return true;
          }
          past.current = [...past.current.slice(-99), problem];
          future.current = [];
          drag.current = { type: "vertex", sel, index: i };
          return true;
        }
      }
      for (let i = 0; i < ring.length; i += 1) {
        const a = ring[i], b = ring[(i + 1) % ring.length];
        const m = at([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
        if (Math.hypot(m[0] - s[0], m[1] - s[1]) <= HANDLE_PX) {
          const mid: Pt = roundPt([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          past.current = [...past.current.slice(-99), problem];
          future.current = [];
          setRing(sel, [...ring.slice(0, i + 1), mid, ...ring.slice(i + 1)], false);
          drag.current = { type: "vertex", sel, index: i + 1 };
          return true;
        }
      }
    }
    const found = hit(raw, at);
    setSel(found);
    if (found) setTab("shapes");
    // The boundary is selected, not moved: a drag from inside the camp pans, as on empty ground.
    if (!found || found.kind === "boundary") return false;
    past.current = [...past.current.slice(-99), problem];
    future.current = [];
    if (found.kind === "door") {
      const door = problem.doors.find((d) => d.id === found.id)!;
      const wall = nearestWall([(door.a[0] + door.b[0]) / 2, (door.a[1] + door.b[1]) / 2], problem.boundary, 0.05);
      if (wall) drag.current = { type: "door-move", id: door.id, start: raw, a: door.a, b: door.b, wall: wall.wall };
      return true;
    }
    drag.current = { type: "move", sel: found, start: raw, ring: ringOf(found)! };
    return true;
  };

  const onMove = (raw: Pt, e: React.PointerEvent) => {
    const p = e.altKey ? roundPt(raw) : snap(raw, snapStep);
    const last = draft[draft.length - 1];
    setHover(e.shiftKey && last && tool !== "select" ? orthogonal(last, p) : p);
    const d = drag.current;
    if (!d) return;
    if (d.type === "place") {
      // The camp follows the pointer over the imagery: the origin moves with it, the view with it.
      const dx = (e.clientX - d.x) * d.view.mpp, dy = -(e.clientY - d.y) * d.view.mpp;
      const origin = toLonLat([-dx, -dy], d.origin, problem.bearing ?? 0);
      setProblemState((q) => ({ ...q, origin_lonlat: [Number(origin[0].toFixed(7)), Number(origin[1].toFixed(7))] }));
      setView({ ...d.view, cx: d.view.cx - dx, cy: d.view.cy - dy });
      return;
    }
    if (d.type === "vertex") {
      const ring = ringOf(d.sel);
      if (!ring) return;
      const prev = ring[(d.index - 1 + ring.length) % ring.length];
      const point = e.shiftKey ? orthogonal(prev, p) : p;
      setRing(d.sel, ring.map((q, k) => (k === d.index ? point : q)), false);
    } else if (d.type === "move") {
      const dx = snapStep ? Math.round((raw[0] - d.start[0]) / snapStep) * snapStep : raw[0] - d.start[0];
      const dy = snapStep ? Math.round((raw[1] - d.start[1]) / snapStep) * snapStep : raw[1] - d.start[1];
      setRing(d.sel, d.ring.map((q) => roundPt([q[0] + dx, q[1] + dy])), false);
    } else if (d.type === "door-end") {
      const door = problem.doors.find((x) => x.id === d.id);
      if (!door) return;
      const moved = roundPt(onWall(p, d.wall));
      setDoor({ ...door, [d.end]: moved }, false);
    } else if (d.type === "door-move") {
      const horizontal = d.wall[0][1] === d.wall[1][1];
      const axis = horizontal ? 0 : 1;
      const lo = Math.min(d.wall[0][axis], d.wall[1][axis]), hi = Math.max(d.wall[0][axis], d.wall[1][axis]);
      let shift = raw[axis] - d.start[axis];
      if (snapStep) shift = Math.round(shift / snapStep) * snapStep;
      const a0 = Math.min(d.a[axis], d.b[axis]), b0 = Math.max(d.a[axis], d.b[axis]);
      shift = Math.max(lo - a0, Math.min(hi - b0, shift));
      const mv = (q: Pt): Pt => roundPt(horizontal ? [q[0] + shift, q[1]] : [q[0], q[1] + shift]);
      const door = problem.doors.find((x) => x.id === d.id);
      if (door) setDoor({ ...door, a: mv(d.a), b: mv(d.b) }, false);
    } else {
      setDragShape({ ...d });
    }
  };

  const onUp = (raw: Pt, e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    setDragShape(null);
    if (!d) return;
    const p = e.altKey ? roundPt(raw) : snap(raw, snapStep);
    if (d.type === "rect") {
      if (Math.abs(p[0] - d.start[0]) > 0.05 && Math.abs(p[1] - d.start[1]) > 0.05) finishRing(rectangle(d.start, p).map((q) => roundPt(q)));
    } else if (d.type === "circle") {
      const r = length(d.start, raw);
      if (r > 0.1) finishRing(circle(d.start, Number(r.toFixed(2))));
    } else if (d.type === "door-end") {
      const door = problem.doors.find((x) => x.id === d.id);
      if (door) {
        const sorted = [door.a, door.b].sort((u, v) => u[0] - v[0] || u[1] - v[1]);
        if (length(sorted[0], sorted[1]) < 0.3) { undo(); setMessage("A door is at least 0.3 m wide."); }
        else setDoor({ ...door, a: sorted[0], b: sorted[1] }, false);
      }
    }
  };

  // Keys: tools, undo, delete, finish, cancel, save.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable=true]")) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); void save(); return; }
      if (mod || mode !== "draw") return;
      if (e.key === "Escape") { if (draft.length) setDraft([]); else { setSel(null); setTool("select"); } return; }
      if (e.key === "Enter" && draft.length >= 3) { finishRing(draft); return; }
      if ((e.key === "Delete" || e.key === "Backspace")) {
        if (draft.length) setDraft(draft.slice(0, -1));
        else if (sel && canEdit) remove(sel);
        return;
      }
      const tools: Record<string, Tool> = { v: "select", b: "boundary", d: "door", o: "obstacles", n: "prohibited", z: "placement_zones", p: "place" };
      const t = tools[e.key.toLowerCase()];
      if (t && canEdit) { setTool(t); setDraft([]); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy("Reading the file…");
    setMessage(null);
    try {
      const got = await importCampFile(file, importUnits);
      setProblem({ ...got.problem, name });
      setCheck(got.check);
      setSel(null);
      const v = fitRings(campRings(got.problem), size.current[0], size.current[1]);
      if (v) setView(v);
      setMessage(`Read ${file.name}: ${got.notes.join("; ")}. Review it, then Save.`);
    } catch (e) {
      setMessage(formatApiError(e));
    } finally {
      setBusy(null);
      if (importer.current) importer.current.value = "";
    }
  };

  // -- what is drawn -------------------------------------------------------------------------
  const faulty = useMemo(() => new Set(check.faults.filter((f) => f.severity === "error").map((f) => f.where)), [check]);
  const result = solve.data?.result ?? null;
  const showLayout = mode === "layout" && result;
  const drawnProblem = showLayout && solve.data ? solve.data.problem : problem;

  const drawing = (at: At, mpp: number) => {
    atRef.current = at;
    const handle = (p: Pt, key: string, kind: "vertex" | "mid" = "vertex") => {
      const [x, y] = at(p);
      return kind === "vertex"
        ? <rect key={key} x={x - 4.5} y={y - 4.5} width={9} height={9} fill="#fff" stroke="#2563eb" strokeWidth={1.5} />
        : <circle key={key} cx={x} cy={y} r={3.5} fill="#2563eb" opacity={0.6} />;
    };
    const selected = (s: Selection) => sameSel(sel, s);
    const labels = layers.labels && mpp < 0.6;
    const label = (p: Pt, text: string, key: string, colour = "#0f172a") => {
      const [x, y] = at(p);
      return (
        <text key={key} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize={11} fontWeight={600} fill={colour}
          stroke="#fff" strokeWidth={3} paintOrder="stroke" pointerEvents="none">{text}</text>
      );
    };
    const out: JSX.Element[] = [];
    out.push(
      <defs key="defs">
        <pattern id="camp-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="rgba(254,226,226,0.6)" />
          <line x1="0" y1="0" x2="0" y2="8" stroke="#dc2626" strokeWidth="2" />
        </pattern>
      </defs>,
    );
    out.push(<path key="boundary" d={ringPath(at, drawnProblem.boundary)} fill={STYLE.boundary.fill}
      stroke={faulty.has("boundary") ? "#dc2626" : STYLE.boundary.stroke} strokeWidth={selected({ kind: "boundary" }) ? 3 : 2} />);
    if (showLayout) {
      out.push(<ResultLayers key="result" at={at} result={result} colourBy={colourBy} hoverBed={hoverBed} onHoverBed={setHoverBed}
        showPaths={layers.paths} labels={labels} />);
    } else {
      if (layers.zones)
        for (const z of check.derived.door_zones) {
          out.push(<path key={`zmax-${z.door}`} d={ringPath(at, z.max_depth)} fill="none" stroke={STYLE.zone.stroke} strokeDasharray="5 4" strokeWidth={1.2} />);
          out.push(<path key={`z-${z.door}`} d={ringPath(at, z.depth)} fill={STYLE.zone.fill} stroke={STYLE.zone.stroke} strokeWidth={1} />);
        }
      for (const kind of ["placement_zones", "prohibited", "obstacles"] as ShapeKind[])
        for (const s of drawnProblem[kind]) {
          const bad = faulty.has(`${FAULT_PREFIX[kind]} ${s.id}`);
          out.push(<path key={`${kind}-${s.id}`} d={ringPath(at, s.ring)} fill={STYLE[kind].fill}
            stroke={bad ? "#dc2626" : STYLE[kind].stroke} strokeWidth={selected({ kind, id: s.id }) ? 3 : 1.5}
            strokeDasharray={kind === "placement_zones" ? "6 3" : undefined} />);
          if (labels) out.push(label(centroid(s.ring), s.id, `l-${kind}-${s.id}`, kind === "obstacles" ? "#0f172a" : STYLE[kind].stroke));
        }
    }
    for (const d of drawnProblem.doors) {
      const [a, b] = [at(d.a), at(d.b)];
      const bad = faulty.has(`door ${d.id}`);
      out.push(<line key={`door-${d.id}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={bad ? "#dc2626" : STYLE.door}
        strokeWidth={selected({ kind: "door", id: d.id }) ? 9 : 7} strokeLinecap="butt" />);
      if (labels || mpp < 2) {
        const mid: Pt = [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2];
        const [mx, my] = at(mid);
        out.push(<text key={`dl-${d.id}`} x={mx} y={my - 10} textAnchor="middle" fontSize={11} fontWeight={700} fill={STYLE.door}
          stroke="#fff" strokeWidth={3} paintOrder="stroke" pointerEvents="none">{d.id}</text>);
      }
    }
    if (!showLayout && sel) {
      const ring = ringOf(sel);
      if (ring) {
        ring.forEach((p, i) => {
          const q = ring[(i + 1) % ring.length];
          const m: Pt = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
          const [mx, my] = at(m);
          if (labels) out.push(<text key={`len-${i}`} x={mx} y={my + 14} textAnchor="middle" fontSize={10} fill="#1d4ed8" stroke="#fff"
            strokeWidth={3} paintOrder="stroke" pointerEvents="none">{length(p, q).toFixed(2)} m</text>);
          if (canEdit) out.push(handle(m, `mid-${i}`, "mid"));
        });
        if (canEdit) ring.forEach((p, i) => out.push(handle(p, `v-${i}`)));
      }
      if (sel.kind === "door" && canEdit) {
        const d = problem.doors.find((x) => x.id === sel.id);
        if (d) { out.push(handle(d.a, "door-a")); out.push(handle(d.b, "door-b")); }
      }
    }
    // What is being drawn.
    if (draft.length) {
      const live = hover ? [...draft, hover] : draft;
      out.push(<path key="draft" d={ringPath(at, live, false)} fill="rgba(37,99,235,0.1)" stroke="#2563eb" strokeWidth={2} strokeDasharray="4 3" />);
      draft.forEach((p, i) => out.push(handle(p, `d-${i}`)));
      if (hover) {
        const last = draft[draft.length - 1];
        const [mx, my] = at([(last[0] + hover[0]) / 2, (last[1] + hover[1]) / 2]);
        out.push(<text key="draft-len" x={mx} y={my - 8} textAnchor="middle" fontSize={11} fill="#1d4ed8" stroke="#fff" strokeWidth={3}
          paintOrder="stroke">{length(last, hover).toFixed(2)} m</text>);
      }
    }
    if (dragShape && hover && (dragShape.type === "rect" || dragShape.type === "circle")) {
      const ring = dragShape.type === "rect" ? rectangle(dragShape.start, hover) : circle(dragShape.start, length(dragShape.start, hover));
      out.push(<path key="drag-shape" d={ringPath(at, ring)} fill="rgba(37,99,235,0.12)" stroke="#2563eb" strokeWidth={2} strokeDasharray="4 3" />);
      const c = at(hover);
      out.push(<text key="drag-size" x={c[0] + 10} y={c[1] - 10} fontSize={11} fill="#1d4ed8" stroke="#fff" strokeWidth={3} paintOrder="stroke">
        {dragShape.type === "rect"
          ? `${Math.abs(hover[0] - dragShape.start[0]).toFixed(2)} × ${Math.abs(hover[1] - dragShape.start[1]).toFixed(2)} m`
          : `r ${length(dragShape.start, hover).toFixed(2)} m`}
      </text>);
    }
    if (tool === "door" && hover && mode === "draw") {
      const pts = doorAt(hover, problem.boundary, 2, snapStep, 25 * mpp + 0.5);
      if (pts) {
        const [a, b] = [at(pts[0]), at(pts[1])];
        out.push(<line key="door-preview" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={STYLE.door} strokeWidth={7} opacity={0.45} />);
      }
    }
    return out;
  };

  const toolButton = (t: Tool, icon: JSX.Element, text: string, key: string) => (
    <button key={t} type="button" aria-pressed={tool === t} title={`${text} (${key})`} disabled={!canEdit && t !== "select"}
      onClick={() => { setTool(t); setDraft([]); setMode("draw"); }}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium ${tool === t ? "bg-blue-600 text-white" : "text-slate-700 hover:bg-slate-100"} disabled:opacity-40`}>
      {icon}<span className="hidden xl:inline">{text}</span>
    </button>
  );
  const drawsShapes = tool === "obstacles" || tool === "prohibited" || tool === "placement_zones" || tool === "boundary";
  const hint = mode === "layout" ? "The layout on the map. Hover a bed to see its route to its door."
    : tool === "select" ? "Click a shape to select it: drag its corners or the dots between them, drag it to move it, Alt-click a corner to remove it. Drag empty ground to pan; scroll to zoom."
    : tool === "door" ? "Click on a horizontal or vertical wall to put a 2 m door there; then drag its ends or type its numbers."
    : tool === "place" ? "Drag the camp over the imagery to put it where it is on the ground."
    : form === "polygon" || tool === "boundary" && form === "circle" ? "Click to add corners; click the first corner, double-click or press Enter to finish. Hold Shift for straight walls, Alt to ignore the snap."
    : form === "rectangle" ? "Drag from one corner to the opposite corner." : "Drag from the centre out to the edge.";

  const errors = check.faults.filter((f) => f.severity === "error");
  const warnings = check.faults.filter((f) => f.severity === "warning");
  const selDoor = sel?.kind === "door" ? problem.doors.find((d) => d.id === sel.id) : undefined;
  const selShape = sel && sel.kind !== "door" && sel.kind !== "boundary" ? problem[sel.kind].find((s) => s.id === sel.id) : undefined;
  const changedSince = solve.data && JSON.stringify(solve.data.problem) !== JSON.stringify({ ...problem, name: solve.data.problem.name });

  const selectFault = (where: string) => {
    if (where === "boundary") return setSel({ kind: "boundary" });
    const door = /^door (.+)$/.exec(where);
    if (door && problem.doors.some((d) => d.id === door[1])) return setSel({ kind: "door", id: door[1] });
    for (const kind of ["obstacles", "prohibited", "placement_zones"] as ShapeKind[]) {
      const m = new RegExp(`^${FAULT_PREFIX[kind]} (.+)$`).exec(where);
      if (m && problem[kind].some((s) => s.id === m[1])) return setSel({ kind, id: m[1] });
    }
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[560px] flex-col gap-2">
      <header className="flex flex-wrap items-center gap-2">
        <Link to={`/domains/${plan.domain_id}/map-data`} className="text-sm text-blue-700 hover:underline">Map data</Link>
        <span className="text-slate-400">/</span>
        <Link to={`/domains/${plan.domain_id}/map-data/camps`} className="text-sm text-blue-700 hover:underline">Camps</Link>
        <span className="text-slate-400">/</span>
        <h1 className="text-lg font-semibold text-slate-900">{name}</h1>
        <span className={`rounded-full px-2 py-0.5 text-xs ${check.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
          {check.ok ? "Ready to lay out" : `${errors.length} to fix`}
        </span>
        {dirty && <span className="text-xs text-amber-700">Unsaved changes</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5" role="group" aria-label="What the map shows">
            <button type="button" aria-pressed={mode === "draw"} onClick={() => setMode("draw")}
              className={`rounded px-2.5 py-1 text-xs font-medium ${mode === "draw" ? "bg-slate-800 text-white" : "text-slate-700"}`}>Drawing</button>
            <button type="button" aria-pressed={mode === "layout"} disabled={!result} onClick={() => setMode("layout")}
              className={`rounded px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${mode === "layout" ? "bg-slate-800 text-white" : "text-slate-700"}`}>Layout</button>
          </div>
          {canEdit && (
            <button type="button" onClick={() => void save()} disabled={!dirty || !!busy}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50">
              <Save className="h-4 w-4" aria-hidden /> Save
            </button>
          )}
          {canSolve && (
            <button type="button" onClick={() => void startSolve()} disabled={!check.ok || !!busy || ["queued", "running"].includes(solve.data?.status ?? "")}
              className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              <Play className="h-4 w-4" aria-hidden /> Lay out camp
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1" role="toolbar" aria-label="Drawing tools">
        {toolButton("select", <MousePointer2 className="h-4 w-4" aria-hidden />, "Select", "V")}
        <span className="mx-1 h-5 w-px bg-slate-200" />
        {toolButton("boundary", <Hexagon className="h-4 w-4" aria-hidden />, "Camp boundary", "B")}
        {toolButton("door", <DoorOpen className="h-4 w-4" aria-hidden />, "Door", "D")}
        {toolButton("obstacles", <Square className="h-4 w-4 fill-slate-500" aria-hidden />, "Closed area", "O")}
        {toolButton("prohibited", <Square className="h-4 w-4 text-red-600" aria-hidden />, "No-beds area", "N")}
        {toolButton("placement_zones", <Pentagon className="h-4 w-4 text-purple-700" aria-hidden />, "Bed zone", "Z")}
        {toolButton("place", <Move className="h-4 w-4" aria-hidden />, "Place on map", "P")}
        {drawsShapes && (
          <div className="ml-1 inline-flex rounded border border-slate-200" role="group" aria-label="Shape">
            {([["polygon", <Pentagon key="p" className="h-3.5 w-3.5" />, "Polygon"], ["rectangle", <Square key="r" className="h-3.5 w-3.5" />, "Rectangle"],
              ...(tool === "obstacles" ? [["circle", <CircleIcon key="c" className="h-3.5 w-3.5" />, "Circle"]] : [])] as [Form, JSX.Element, string][]).map(([f, icon, text]) => (
              <button key={f} type="button" aria-pressed={form === f} title={text} onClick={() => { setForm(f); setDraft([]); }}
                className={`inline-flex items-center gap-1 px-2 py-1 text-xs ${form === f ? "bg-slate-800 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
                {icon}<span className="hidden 2xl:inline">{text}</span>
              </button>
            ))}
          </div>
        )}
        <span className="mx-1 h-5 w-px bg-slate-200" />
        <button type="button" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!past.current.length} onClick={undo}
          className="rounded p-1.5 text-slate-700 hover:bg-slate-100 disabled:opacity-30"><Undo2 className="h-4 w-4" /></button>
        <button type="button" title="Redo (Ctrl+Y)" aria-label="Redo" disabled={!future.current.length} onClick={redo}
          className="rounded p-1.5 text-slate-700 hover:bg-slate-100 disabled:opacity-30"><Redo2 className="h-4 w-4" /></button>
        <button type="button" title="Fit the camp in view" aria-label="Fit the camp in view" onClick={fit}
          className="rounded p-1.5 text-slate-700 hover:bg-slate-100"><Maximize2 className="h-4 w-4" /></button>
        <label className="ml-1 text-xs text-slate-600">
          Snap
          <select value={snapStep} onChange={(e) => setSnapStep(Number(e.target.value))} className="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5">
            {SNAPS.map((s) => <option key={s} value={s}>{s ? `${s} m` : "off"}</option>)}
          </select>
        </label>
        <label className="ml-2 inline-flex items-center gap-1 text-xs text-slate-600">
          <MapIcon className="h-3.5 w-3.5" aria-hidden />
          <select value={basemap.chosen?.id ?? "none"} onChange={(e) => basemap.choose(e.target.value)} aria-label="Background"
            className="rounded border border-slate-300 bg-white px-1 py-0.5">
            {basemap.options.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            <option value="none">No background</option>
          </select>
        </label>
        <details className="relative ml-1">
          <summary className="inline-flex cursor-pointer items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-700 hover:bg-slate-100">
            <Layers className="h-3.5 w-3.5" aria-hidden /> Layers
          </summary>
          <div className="absolute z-20 mt-1 w-48 rounded-md border border-slate-200 bg-white p-2 text-xs shadow-lg">
            {([["zones", "Door zones"], ["labels", "Names and lengths"], ["paths", "Walking routes (layout)"]] as const).map(([k, text]) => (
              <label key={k} className="flex items-center gap-1.5 py-0.5">
                <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} /> {text}
              </label>
            ))}
          </div>
        </details>
        <span className="ml-auto flex items-center gap-1">
          {canEdit && (
            <>
              <select value={importUnits} onChange={(e) => setImportUnits(e.target.value)} aria-label="Units of a drawing to import"
                className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs" title="Units of a drawing to import">
                <option value="">units from drawing</option><option value="mm">mm</option><option value="cm">cm</option><option value="m">m</option>
              </select>
              <button type="button" onClick={() => importer.current?.click()} title="Replace the drawing with a .dxf or .xlsx"
                className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-700 hover:bg-slate-100">
                <FileUp className="h-3.5 w-3.5" aria-hidden /> Import
              </button>
              <input ref={importer} type="file" accept=".dxf,.xlsx" className="hidden" aria-label="Drawing or workbook to import"
                onChange={(e) => void importFile(e.target.files?.[0])} />
            </>
          )}
          <details className="relative">
            <summary className="inline-flex cursor-pointer items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-700 hover:bg-slate-100">
              <Download className="h-3.5 w-3.5" aria-hidden /> Export
            </summary>
            <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-slate-200 bg-white p-1 text-xs shadow-lg">
              {([["xlsx", "Workbook (.xlsx)"], ["dxf", "CAD drawing (.dxf)"], ["json", "Problem (.json)"]] as const).map(([f, text]) => (
                <button key={f} type="button" className="block w-full rounded px-2 py-1 text-left hover:bg-slate-100"
                  onClick={() => void downloadFrom(`/api/v1/camps/${plan.id}/export?format=${f}`).catch((e) => setMessage(formatApiError(e)))}>
                  {text}{dirty ? " — as last saved" : ""}
                </button>
              ))}
            </div>
          </details>
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-3">
        <div className="relative min-w-0 flex-1">
          <CampMap
            origin={drawnProblem.origin_lonlat}
            bearing={drawnProblem.bearing ?? 0}
            view={view}
            onView={setView}
            basemap={basemap.chosen}
            height="100%"
            cursor={mode === "layout" ? "default" : tool === "select" ? "default" : tool === "place" ? "move" : "crosshair"}
            onDown={onDown}
            onMove={onMove}
            onUp={onUp}
            onDoubleClick={() => { if (draft.length >= 3) finishRing(draft); }}
            onSize={onSize}
            label={`Map of ${name}`}
            overlay={
              <div className="pointer-events-none absolute left-2 top-2 max-w-[70%] space-y-1">
                <p className="rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow-sm">{hint}</p>
                {message && <p role="status" className="pointer-events-auto rounded bg-amber-50/95 px-2 py-1 text-xs text-amber-900 shadow-sm">{message}</p>}
                {busy && <p className="rounded bg-blue-50/95 px-2 py-1 text-xs text-blue-900 shadow-sm">{busy}</p>}
                {mode === "layout" && changedSince && (
                  <p className="rounded bg-amber-50/95 px-2 py-1 text-xs text-amber-900 shadow-sm">
                    The drawing has changed since this layout was made; lay it out again to see the change.
                  </p>
                )}
              </div>
            }
          >
            {drawing}
          </CampMap>
        </div>

        <aside className="flex w-[380px] shrink-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="Camp details">
          <div className="flex border-b border-slate-200 text-xs font-medium" role="tablist">
            {([["shapes", "Shapes"], ["beds", "Beds"], ["settings", "Settings"], ["solve", "Layout"]] as const).map(([k, text]) => (
              <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`flex-1 px-2 py-2 ${tab === k ? "border-b-2 border-blue-600 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>
                {text}{k === "shapes" && errors.length ? ` (${errors.length})` : ""}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm">
            {tab === "shapes" && (
              <div className="space-y-3">
                {(errors.length > 0 || warnings.length > 0) && (
                  <section aria-label="Checks" className="space-y-1">
                    {[...errors, ...warnings].map((f, i) => (
                      <button key={i} type="button" onClick={() => selectFault(f.where)}
                        className={`block w-full rounded px-2 py-1 text-left text-xs ${f.severity === "error" ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900"}`}>
                        <strong>{f.where}</strong> {f.message}
                      </button>
                    ))}
                  </section>
                )}
                {check.ok && (
                  <p className="rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-800">
                    {check.derived.area_m2?.toLocaleString()} m² inside the walls, {check.derived.cells?.toLocaleString()} grid cells. Ready to lay out.
                  </p>
                )}

                {sel && (
                  <section className="rounded-lg border border-blue-200 bg-blue-50/40 p-2" aria-label="Selected shape">
                    <div className="mb-2 flex items-center justify-between">
                      <h2 className="text-sm font-semibold text-slate-900">
                        {sel.kind === "boundary" ? "Camp boundary" : sel.kind === "door" ? `Door ${sel.id}` : `${KIND_LABEL[sel.kind]} ${sel.id}`}
                      </h2>
                      {sel.kind !== "boundary" && canEdit && (
                        <button type="button" onClick={() => remove(sel)} className="text-xs text-red-700 hover:underline">Delete</button>
                      )}
                    </div>
                    {sel.kind === "boundary" && (
                      <CoordTable label="Corners" ring={problem.boundary} onChange={(ring) => setProblem((p) => ({ ...p, boundary: ring }))} />
                    )}
                    {selDoor && (
                      <DoorPanel door={selDoor} zone={zoneOf(selDoor.id)} taken={problem.doors.map((d) => d.id)}
                        onDoor={(d) => setDoor(d)}
                        onZone={(z) => setProblem((p) => ({ ...p, zones: p.zones.some((x) => x.door === z.door) ? p.zones.map((x) => (x.door === z.door ? z : x)) : [...p.zones, z] }))}
                        onRename={(newId) => {
                          setProblem((p) => ({ ...p, doors: p.doors.map((d) => (d.id === selDoor.id ? { ...d, id: newId } : d)),
                            zones: p.zones.map((z) => (z.door === selDoor.id ? { ...z, door: newId } : z)) }));
                          setSel({ kind: "door", id: newId });
                        }} />
                    )}
                    {selShape && sel.kind !== "door" && sel.kind !== "boundary" && (
                      <ShapePanel shape={selShape} kind={sel.kind} taken={problem[sel.kind].map((s) => s.id)}
                        bedTypes={problem.bed_types}
                        onAssign={(typeId, on) => setProblem((p) => ({ ...p, bed_types: p.bed_types.map((b) => (b.id === typeId ? { ...b, zone: on ? selShape.id : null } : b)) }))}
                        onChange={(s) => setProblem((p) => ({ ...p, [sel.kind]: p[sel.kind as ShapeKind].map((x) => (x.id === selShape.id ? s : x)) }))}
                        onRename={(newId) => {
                          const kind = sel.kind as ShapeKind;
                          setProblem((p) => ({
                            ...p, [kind]: p[kind].map((x) => (x.id === selShape.id ? { ...x, id: newId } : x)),
                            bed_types: kind === "placement_zones" ? p.bed_types.map((b) => (b.zone === selShape.id ? { ...b, zone: newId } : b)) : p.bed_types,
                          }));
                          setSel({ kind, id: newId });
                        }} />
                    )}
                  </section>
                )}

                <ShapeList title="Doors" items={problem.doors.map((d) => ({ id: d.id, note: `${length(d.a, d.b).toFixed(2)} m${d.capacity ? ` · up to ${d.capacity} beds` : ""}` }))}
                  selected={sel?.kind === "door" ? sel.id : null} onPick={(i) => setSel({ kind: "door", id: i })}
                  empty="Choose Door and click on a wall." swatch={<span className="inline-block h-1.5 w-4 bg-emerald-600" />} />
                {(["obstacles", "prohibited", "placement_zones"] as ShapeKind[]).map((kind) => (
                  <ShapeList key={kind} title={`${KIND_LABEL[kind]}s`}
                    items={problem[kind].map((s) => ({ id: s.id, note: `${area(s.ring).toFixed(1)} m²` }))}
                    selected={sel?.kind === kind ? sel.id : null} onPick={(i) => setSel({ kind, id: i })}
                    empty={kind === "obstacles" ? "Latrines, generators, tanks, trees: nothing goes here." : kind === "prohibited" ? "Fire breaks, clear lanes: people walk, no beds." : "Where a bed type must go."}
                    swatch={<span className={`inline-block h-3 w-3 border ${kind === "obstacles" ? "border-slate-800 bg-slate-500" : kind === "prohibited" ? "border-red-700 bg-red-100" : "border-dashed border-purple-700 bg-purple-100"}`} />} />
                ))}
                <button type="button" className="text-xs text-blue-700 hover:underline" onClick={() => setSel({ kind: "boundary" })}>
                  Camp boundary: {problem.boundary.length} corners, {area(problem.boundary).toFixed(1)} m²
                </button>
                <CampRecords plan={plan} />
              </div>
            )}
            {tab === "beds" && (
              <BedTypesPanel problem={problem} onChange={(types) => setProblem((p) => ({ ...p, bed_types: types }))} />
            )}
            {tab === "settings" && (
              <SettingsPanel problem={problem} name={name} onName={setName}
                onChange={(p) => setProblem(p)} />
            )}
            {tab === "solve" && (
              <ResultPanel
                plan={plan}
                options={options}
                onOptions={setOptions}
                solve={solve.data ?? null}
                onPickSolve={(sid) => { setSolveId(sid); setMode("layout"); }}
                onCancel={async () => { if (solveId) { await cancelCampSolve(solveId); void solve.refetch(); } }}
                onShow={() => setMode("layout")}
                colourBy={colourBy}
                onColourBy={setColourBy}
                hoverBed={hoverBed}
                canSolve={canSolve && check.ok}
                onSolve={() => void startSolve()}
              />
            )}
          </div>
        </aside>
      </div>
      {mode === "layout" && result && <ResultLegend result={result} colourBy={colourBy} />}
    </div>
  );
}

function ShapeList({ title, items, selected, onPick, empty, swatch }: {
  title: string;
  items: { id: string; note: string }[];
  selected: string | null;
  onPick: (id: string) => void;
  empty: string;
  swatch: JSX.Element;
}) {
  return (
    <section>
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{swatch} {title} ({items.length})</h3>
      {items.length === 0 ? <p className="mt-1 text-xs text-slate-400">{empty}</p> : (
        <ul className="mt-1 divide-y divide-slate-100 rounded border border-slate-200">
          {items.map((i) => (
            <li key={i.id}>
              <button type="button" onClick={() => onPick(i.id)}
                className={`flex w-full items-center justify-between px-2 py-1 text-left text-xs ${selected === i.id ? "bg-blue-50 font-semibold text-blue-900" : "hover:bg-slate-50"}`}>
                <span>{i.id}</span><span className="text-slate-500">{i.note}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const RECORD_WORDS: [string, string][] = [
  ["camp", "camp"], ["door", "doors"], ["closed_area", "closed areas"], ["no_beds_area", "no-beds areas"],
  ["bed_zone", "bed zones"], ["bed_type", "bed types"],
];

/** Where this camp lives in the domain: its records, linked to the Records page by type. */
function CampRecords({ plan }: { plan: CampPlan }) {
  if (!plan.records) return null;
  const { types, counts } = plan.records;
  return (
    <section className="rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700" aria-label="This camp's records">
      <h3 className="font-semibold text-slate-800">Kept as records of this domain</h3>
      <p className="mt-0.5 text-slate-500">
        Saved, the camp is records you can also edit on the Records, Relationships and Parameters pages
        (door capacities, zone depths and bed counts are parameters).
      </p>
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
        {RECORD_WORDS.filter(([t]) => types[t]).map(([t, words]) => (
          <li key={t}>
            <Link className="text-blue-700 hover:underline" to={`/domains/${plan.domain_id}/data/records?type=${types[t]}`}>
              {counts[t] ?? 0} {words}
            </Link>
          </li>
        ))}
        <li><Link className="text-blue-700 hover:underline" to={`/domains/${plan.domain_id}/data/parameters`}>parameters</Link></li>
        <li><Link className="text-blue-700 hover:underline" to={`/domains/${plan.domain_id}/data/relationships`}>relationships</Link></li>
      </ul>
    </section>
  );
}
