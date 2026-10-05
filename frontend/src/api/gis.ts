/**
 * Map data (DXF -> GIS): `/api/v1/gis/...` (backend `app/api/gis.py`).
 *
 * Upload a drawing, see its layers and where each coordinate system would
 * put it, preview a placement on the map, import it as layers of features,
 * then view, restyle, place again or export them.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LonLat = [number, number];
export type GisPlacement =
  | { kind: "epsg"; code: number; units?: number; name?: string }
  | { kind: "local"; anchor: [number, number]; lonlat: LonLat; rotation: number; scale: number; units?: number };

export type CadLayerSummary = {
  name: string;
  color: string;
  linetype: string;
  on: boolean;
  frozen: boolean;
  locked: boolean;
  kinds: Record<string, number>;
  entities: Record<string, number>;
  features: number;
};
export type CadSummary = {
  version: string;
  units_code: number;
  units_name: string | null;
  unit_metres: number | null;
  extent: [number, number, number, number] | null;
  layers: CadLayerSummary[];
  kinds: Record<string, number>;
  features: number;
  geodata: Record<string, unknown> | null;
  notes: string[];
  skipped: Record<string, number>;
};
export type CrsCandidate = {
  placement: { kind: "epsg"; code: number };
  name: string;
  area: string | null;
  reason: string;
  centre: LonLat;
  fits: boolean;
  score: number;
  /** Other systems (other datums) that put the drawing within 3 km of the same place. */
  also?: string[];
  /** Unambiguous: a form may choose it without asking. */
  sure?: boolean;
};
export type SiteWhere = { region: string | null; point: LonLat | null };
export type GisUpload = {
  upload_id: string;
  filename: string;
  size_bytes: number;
  summary: CadSummary;
  candidates: CrsCandidate[];
  utm_zones: { code: number; zone: string; centre: LonLat }[];
  unit_choices: Record<string, number>;
};
export type GisFeature = {
  type: "Feature";
  id?: number;
  geometry: { type: "Point" | "LineString" | "Polygon"; coordinates: unknown };
  properties: Record<string, unknown> & { layer: string; kind: string; layer_id?: number; color?: string; text?: string };
};
export type GisPreview = {
  placement: GisPlacement;
  bbox: [number, number, number, number] | null;
  features: { type: "FeatureCollection"; features: GisFeature[] };
  sampled: boolean;
  total: number;
  warnings: string[];
  repaired: number;
  dropped: number;
};
export type GisLayer = {
  id: number;
  name: string;
  color: string;
  visible: boolean;
  kinds: Record<string, number>;
  feature_count: number;
  sort_order: number;
};
export type GisDataset = {
  id: number;
  domain_id: number;
  name: string;
  source: { filename?: string; format?: string; size_bytes?: number; version?: string; units?: string | null;
    unit_metres?: number | null; extent?: number[] | null };
  placement: GisPlacement;
  bbox: [number, number, number, number] | null;
  stats: { features?: number; kinds?: Record<string, number>; skipped?: Record<string, number>; repaired?: number; dropped?: number };
  notes: string[];
  created_at: string;
  updated_at: string;
  layers: GisLayer[];
  postgis: boolean;
};
export type GisDatasetItem = Omit<GisDataset, "layers" | "postgis"> & { layers: number };
export type CrsInfo = { code: number; name: string; area: string | null; type?: string };

const GIS = "gis";
const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export function uploadDrawing(file: File, domainId: number, region: string | null = null): Promise<GisUpload> {
  const form = new FormData();
  form.append("file", file);
  form.append("domain_id", String(domainId));
  form.append("region", region ?? "");
  return apiFetch<GisUpload>("/api/v1/gis/uploads", { method: "POST", body: form });
}
export const uploadCandidates = (id: string, where: SiteWhere) =>
  apiFetch<{ candidates: CrsCandidate[] }>(`/api/v1/gis/uploads/${id}/candidates`, { method: "POST", ...json(where) });
export type SiteRegion = { name: string; bbox: number[]; places: { name: string; lonlat: LonLat }[] };
export const listRegions = () => apiFetch<{ items: SiteRegion[] }>("/api/v1/gis/regions");
export function useRegions() {
  return useQuery({ queryKey: [GIS, "regions"], queryFn: listRegions, staleTime: Infinity });
}
export const previewUpload = (id: string, body: { placement: GisPlacement; units?: number | null; layers?: string[] }) =>
  apiFetch<GisPreview>(`/api/v1/gis/uploads/${id}/preview`, { method: "POST", ...json(body) });
export const importDataset = (body: {
  upload_id: string; domain_id: number; name: string; placement: GisPlacement; units?: number | null; layers?: string[];
}) => apiFetch<GisDataset>("/api/v1/gis/datasets", { method: "POST", ...json(body) });
export const listDatasets = (domainId: number) =>
  apiFetch<{ items: GisDatasetItem[]; postgis: boolean }>(`/api/v1/gis/datasets?domain_id=${domainId}`);
export const getDataset = (id: number) => apiFetch<GisDataset>(`/api/v1/gis/datasets/${id}`);
export const getFeatures = (id: number) =>
  apiFetch<{ type: "FeatureCollection"; truncated: boolean; features: GisFeature[] }>(`/api/v1/gis/datasets/${id}/features`);
export const placeDataset = (id: number, placement: GisPlacement, units?: number | null) =>
  apiFetch<GisDataset>(`/api/v1/gis/datasets/${id}/placement`, { method: "PUT", ...json({ placement, units }) });
export const datasetCandidates = (id: number, where: SiteWhere = { region: null, point: null }) => {
  const q = new URLSearchParams();
  if (where.region) q.set("region", where.region);
  if (where.point) { q.set("lon", String(where.point[0])); q.set("lat", String(where.point[1])); }
  return apiFetch<{ candidates: CrsCandidate[]; utm_zones: GisUpload["utm_zones"]; extent: [number, number, number, number] | null; units: string | null }>(
    `/api/v1/gis/datasets/${id}/candidates?${q}`);
};
export const renameDataset = (id: number, name: string) =>
  apiFetch<GisDataset>(`/api/v1/gis/datasets/${id}`, { method: "PATCH", ...json({ name }) });
export const deleteDataset = (id: number) => apiFetch<void>(`/api/v1/gis/datasets/${id}`, { method: "DELETE" });
export const editLayer = (id: number, body: { name?: string; color?: string; visible?: boolean }) =>
  apiFetch<GisLayer>(`/api/v1/gis/layers/${id}`, { method: "PATCH", ...json(body) });
export const searchCrs = (q: string) => apiFetch<{ items: CrsInfo[] }>(`/api/v1/gis/crs?q=${encodeURIComponent(q)}`);

export function useDatasets(domainId: number | null) {
  return useQuery({ queryKey: [GIS, "list", domainId], queryFn: () => listDatasets(domainId as number), enabled: domainId !== null });
}
export function useDataset(id: number | null) {
  return useQuery({ queryKey: [GIS, "dataset", id], queryFn: () => getDataset(id as number), enabled: id !== null });
}
export function useFeatures(id: number | null, version: string | undefined) {
  return useQuery({
    queryKey: [GIS, "features", id, version],
    queryFn: () => getFeatures(id as number),
    enabled: id !== null && !!version,
    staleTime: Infinity,
  });
}
export function useCrsSearch(q: string) {
  return useQuery({ queryKey: [GIS, "crs", q], queryFn: () => searchCrs(q), enabled: q.trim().length >= 2, staleTime: Infinity });
}
export function useGisMutation<V, R>(fn: (vars: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => client.invalidateQueries({ queryKey: [GIS] }) });
}

// --- Map layers as records (improvement plan 1.1 / 1.3) ------------------------------

export type RecordsField = { property: string; name: string; data_type: string; enum_values: string[] | null; samples: string[]; skip: boolean };
export type RecordsProposal = {
  layers: string[]; name: string; exists: boolean; features: number; skipped_text: number; shapes: string[];
  key: string | null; key_candidates: string[]; label?: string | null; fields: RecordsField[]; geometry_field: string;
  measures: string[]; properties: string[];
};
export type RecordsMade = { type: string; entity_type_id: number; domain_id: number; made: number; updated: number };
export type ShapesAttached = { type: string; field: string; attached: number; records_without_shape: string[]; unmatched_features: string[] };

export const proposeRecords = (datasetId: number, layers: string[]) =>
  apiFetch<RecordsProposal>(`/api/v1/gis/datasets/${datasetId}/records/propose`, { method: "POST", ...json({ layers }) });
export const makeRecords = (datasetId: number, layers: string[], plan: RecordsProposal) =>
  apiFetch<RecordsMade>(`/api/v1/gis/datasets/${datasetId}/records`, { method: "POST", ...json({ layers, plan }) });
export const attachShapes = (datasetId: number, body: { layers: string[]; type: string; match: string; field?: string }) =>
  apiFetch<ShapesAttached>(`/api/v1/gis/datasets/${datasetId}/records/attach`, { method: "POST", ...json(body) });

// --- All of a domain's map data onto its kinds of record (backend app/gis/auto_records.py) ----

export type AutoField = { property: string; name: string; data_type: string; enum_values: string[] | null; new: boolean; skip: boolean };
export type AutoMapping = {
  action: "existing" | "new" | "skip"; dataset_id: number; dataset: string; layer: string; features: number; skipped_text: number;
  type: string; confidence: number; reasons: string[]; key: string | null; key_candidates: string[]; label: string | null;
  fields: AutoField[]; geometry_field: string; updates: number; creates: number; create_missing: boolean;
  required_unfilled: string[]; faults: string[]; alternatives: { type: string; confidence: number }[];
};
export type AutoProposal = { domain_id: number; types: string[]; mappings: AutoMapping[] };
export type AutoChoice = { dataset_id: number; layer: string; type: string | null; key?: string | null };
export type AutoApplied = {
  domain_id: number; faults: string[];
  results: { dataset_id: number; layer: string; type: string; entity_type_id: number; made: number; updated: number }[];
};

export const proposeDomainRecords = (domainId: number, choices: AutoChoice[] = [], datasetIds?: number[]) =>
  apiFetch<AutoProposal>(`/api/v1/gis/domains/${domainId}/records/propose`, {
    method: "POST", ...json({ choices, ...(datasetIds ? { dataset_ids: datasetIds } : {}) }) });
export const applyDomainRecords = (domainId: number, mappings: AutoMapping[]) =>
  apiFetch<AutoApplied>(`/api/v1/gis/domains/${domainId}/records`, { method: "POST", ...json({ mappings }) });

/** A new layer made from records: a buffer round each, the places each reaches by 0/1 data, or the places none reaches
 * (benchmark round 5). */
export type DeriveLayer = { domain_id: number; name: string; how: "buffer" | "service_area" | "not_reached"; entity_type_id: number;
  radius_km?: number; parameter_id?: number; keys?: string[] };
export const deriveLayer = (body: DeriveLayer) =>
  apiFetch<GisDataset & { made: number }>("/api/v1/gis/derived-layers", { method: "POST", ...json(body) });
