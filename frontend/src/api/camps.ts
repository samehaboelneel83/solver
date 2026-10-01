/**
 * Camp plans (camp layout engine): a camp drawn on the map, checked, solved
 * by the worker and shown on the map. `GET/POST /api/v1/camps...` and
 * `/api/v1/camp-solves...` (backend `app/api/camps.py`).
 *
 * A problem is `camp-problem/1` JSON in local metres (x east, y north)
 * around `origin_lonlat`; `lib/campGeo` converts to and from the map.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiFetch } from "./client";

export type Pt = [number, number];
export type Ring = Pt[];

export type CampDoor = { id: string; a: Pt; b: Pt; depth?: number; capacity?: number | null };
export type CampDoorZone = {
  door: string;
  depth?: number;
  max_depth?: number;
  step?: number;
  margin?: number;
  area_per_bed?: number | null;
};
export type CampShape = { id: string; ring: Ring; kind?: string };
export type CampBedType = {
  id: string;
  length: number;
  width: number;
  min_length?: number | null;
  max_length?: number | null;
  min_width?: number | null;
  max_width?: number | null;
  sizes?: Pt[];
  rotation?: boolean;
  side_gap?: number;
  min_count?: number;
  max_count?: number | null;
  zone?: string | null;
  priority?: number;
};
export type CampObjectiveName = "beds" | "distance" | "corridor" | "modifications";
export type CampProblem = {
  format?: string;
  name: string;
  grid: number;
  origin_lonlat: Pt;
  boundary: Ring;
  doors: CampDoor[];
  zones: CampDoorZone[];
  obstacles: CampShape[];
  prohibited: CampShape[];
  placement_zones: CampShape[];
  bed_types: CampBedType[];
  corridor: { min_width: number; access: "long_sides" | "any_side" };
  objectives: {
    mode: "lexicographic" | "weighted";
    order: CampObjectiveName[];
    weights: Record<string, number>;
    tolerance: Record<string, number>;
    trade_beds: boolean;
  };
};

export type CampFault = { where: string; message: string; severity: "error" | "warning" };
export type CampDoorZoneShape = { door: string; depth: Ring; max_depth: Ring; area_m2: number; beds_room: number | null };
export type CampCheck = {
  ok: boolean;
  faults: CampFault[];
  derived: { door_zones: CampDoorZoneShape[]; area_m2: number | null; cells: number | null };
};

export type CampSolver = "cpsat" | "scip" | "highs" | "cbc" | "heuristic";
export type CampOptions = { solver: CampSolver; beds_seconds: number; seconds: number; threads: number };

export type CampSolveSummary = {
  id: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  beds: number | null;
  valid: boolean | null;
  error: string | null;
  options: CampOptions;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type CampPlan = {
  id: number;
  domain_id: number;
  name: string;
  problem: CampProblem;
  options: CampOptions;
  created_at: string;
  updated_at: string;
  check: CampCheck;
  solves: CampSolveSummary[];
};

export type CampListItem = {
  id: number;
  name: string;
  updated_at: string;
  origin_lonlat: Pt;
  doors: number;
  solve_id: number | null;
  status: CampSolveSummary["status"] | null;
  beds: number | null;
  valid: boolean | null;
  finished_at: string | null;
};

export type GeoFeature = {
  type: "Feature";
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown> & { layer: string };
};
export type CampCheckRow = { name: string; ok: boolean; detail: string; count?: number };
export type CampReport = {
  camp: string;
  solver: string;
  beds: number;
  beds_by_type: Record<string, number>;
  resized_beds: number;
  stage0_beds: number;
  objectives: Record<string, number>;
  stages: { objective: string; status: string; value?: number; bound?: number; seconds?: number; kept?: string }[];
  zone_depth_m: Record<string, number>;
  validation: {
    valid: boolean;
    checks: CampCheckRow[];
    walk_total_m: number;
    walk_max_m: number;
    walk_mean_m: number;
    door_loads: Record<string, number>;
  };
  seconds: Record<string, number>;
};
export type CampSolve = CampSolveSummary & {
  camp_id: number;
  camp_name: string;
  domain_id: number;
  seconds: number;
  progress: string[];
  deadline_seconds: number;
  problem: CampProblem;
  result: null | {
    input: { type: "FeatureCollection"; features: GeoFeature[] };
    output: { type: "FeatureCollection"; features: GeoFeature[] };
    report: CampReport;
    origin_lonlat: Pt;
    beds: number;
    valid: boolean;
  };
};

export type CampImport = { problem: CampProblem; notes: string[]; offset: Pt; check: CampCheck };

const CAMPS = "camps";
const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const listCamps = (domainId: number) =>
  apiFetch<{ items: CampListItem[] }>(`/api/v1/camps?domain_id=${domainId}`);
export const getCamp = (id: number) => apiFetch<CampPlan>(`/api/v1/camps/${id}`);
export const createCamp = (body: {
  domain_id: number;
  name: string;
  start?: "blank" | "small" | "complex";
  problem?: CampProblem;
  origin_lonlat?: Pt;
}) => apiFetch<CampPlan>("/api/v1/camps", { method: "POST", ...json(body) });
export const saveCamp = (id: number, body: { name?: string; problem?: CampProblem; options?: Partial<CampOptions>; updated_at?: string }) =>
  apiFetch<CampPlan>(`/api/v1/camps/${id}`, { method: "PUT", ...json(body) });
export const deleteCamp = (id: number) => apiFetch<void>(`/api/v1/camps/${id}`, { method: "DELETE" });
export const checkCamp = (problem: CampProblem) =>
  apiFetch<CampCheck>("/api/v1/camps/check", { method: "POST", ...json({ problem }) });
export function importCampFile(file: File, units = "", crs = ""): Promise<CampImport> {
  const form = new FormData();
  form.append("file", file);
  form.append("units", units);
  form.append("crs", crs);
  return apiFetch<CampImport>("/api/v1/camps/import", { method: "POST", body: form });
}
export const solveCamp = (id: number, body: Partial<Omit<CampOptions, "threads">>) =>
  apiFetch<CampSolve>(`/api/v1/camps/${id}/solves`, { method: "POST", ...json(body) });
export const getCampSolve = (id: number) => apiFetch<CampSolve>(`/api/v1/camp-solves/${id}`);
export const cancelCampSolve = (id: number) =>
  apiFetch<CampSolve>(`/api/v1/camp-solves/${id}/cancel`, { method: "POST" });

/** Save a file from the API in the browser. */
export async function downloadFrom(path: string): Promise<void> {
  const { blob, filename } = await apiDownload(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function useCamps(domainId: number | null) {
  return useQuery({
    queryKey: [CAMPS, "list", domainId],
    queryFn: () => listCamps(domainId as number),
    enabled: domainId !== null,
  });
}

export function useCamp(id: number | null) {
  return useQuery({
    queryKey: [CAMPS, "plan", id],
    queryFn: () => getCamp(id as number),
    enabled: id !== null,
    refetchOnWindowFocus: false,
  });
}

/** Asked every 1.5 s while it is queued or running. */
export function useCampSolve(id: number | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [CAMPS, "solve", id],
    queryFn: async () => {
      const solve = await getCampSolve(id as number);
      if (!["queued", "running"].includes(solve.status)) void client.invalidateQueries({ queryKey: [CAMPS, "list"] });
      return solve;
    },
    enabled: id !== null,
    refetchInterval: (query) => {
      const status = (query.state.data as CampSolve | undefined)?.status;
      return !status || status === "queued" || status === "running" ? 1500 : false;
    },
  });
}

function useCampMutation<V, R>(fn: (vars: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => client.invalidateQueries({ queryKey: [CAMPS, "list"] }) });
}

export const useCreateCamp = () => useCampMutation(createCamp);
export const useDeleteCamp = () => useCampMutation(deleteCamp);
