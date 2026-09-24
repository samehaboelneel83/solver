/**
 * A run's partition on a map (GIS 7): cells coloured by group, a totals
 * table beside, and the zones exported as GeoJSON. Drawn from the run's own
 * stored answer (`GET /runs/{id}/map`), never from a guess mid-solve.
 *
 * SVG up to 5,000 cells, where each cell can carry its own tooltip; a
 * canvas beyond, where SVG would be thousands of DOM nodes.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { getRunMap, type Id, type RunMapFeature } from "../../api/v1";
import { NO_BASEMAP, useBasemaps } from "../../hooks/useBasemaps";
import { fitView, tileUrl, type Basemap, type View } from "../../lib/tiles";
import { Card, SkeletonCard, formatNumber, type GenUIProps } from "./shared";

/** Twelve categorical colours, each at least 3:1 against white. */
export const ZONE_COLOURS = [
  "#2563eb", "#d97706", "#059669", "#db2777", "#7c3aed", "#0891b2",
  "#65a30d", "#dc2626", "#4f46e5", "#ca8a04", "#0d9488", "#9333ea",
];
export const SVG_LIMIT = 5000;
const WIDTH = 640;
const HEIGHT = 420;
const HIDDEN = new Set(["group", "subgroup", "cells"]);

type Ring = number[][];

function polygons(feature: RunMapFeature): Ring[][] {
  return feature.geometry.type === "Polygon"
    ? [feature.geometry.coordinates as Ring[]]
    : (feature.geometry.coordinates as Ring[][]);
}

/** Longitude and latitude onto the drawing: a degree of longitude is
 * shorter than one of latitude away from the equator, so x is scaled by
 * the cosine of the middle latitude. A projected CRS (metres) has no such
 * shrink and its y is far from ±90, so the cosine is used only when the
 * numbers look like degrees. */
/**
 * How the cells are drawn: the projection from their coordinates to the
 * frame and, over a basemap, the tiles under them. With a basemap the frame
 * is Web Mercator, so the cells sit on the imagery; without one (or when
 * the coordinates are not degrees -- a projected CRS), a plain projection
 * that corrects a degree of longitude for latitude.
 */
function frameOf(features: RunMapFeature[], basemap: Basemap | null): { at: (p: number[]) => number[]; tiles: View["tiles"] } {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const feature of features)
    for (const rings of polygons(feature))
      for (const ring of rings)
        for (const [x, y] of ring) {
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
        }
  const degrees = Math.abs(minX) <= 180 && Math.abs(maxX) <= 180 && Math.abs(minY) <= 90 && Math.abs(maxY) <= 90;
  if (basemap && degrees) {
    const view = fitView({ west: minX, south: minY, east: maxX, north: maxY }, WIDTH, HEIGHT, basemap);
    return { at: ([x, y]: number[]) => view.project(x, y), tiles: view.tiles };
  }
  const k = degrees ? Math.cos((((minY + maxY) / 2) * Math.PI) / 180) : 1;
  const scale = Math.min(WIDTH / ((maxX - minX) * k || 1), HEIGHT / (maxY - minY || 1));
  return { at: ([x, y]: number[]) => [(x - minX) * k * scale, HEIGHT - (y - minY) * scale], tiles: [] };
}

function pathOf(feature: RunMapFeature, at: (p: number[]) => number[]): string {
  return polygons(feature)
    .flatMap((rings) =>
      rings.map(
        (ring) =>
          ring
            .map((p, i) => {
              const [x, y] = at(p);
              return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ") + "Z"
      )
    )
    .join(" ");
}

function download(name: string, body: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(body)], { type: "application/geo+json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const notSpatial = (error: unknown) => error instanceof ApiError && error.status === 404;

/** The map itself. With `quietIfNone`, a run that has no map (404) shows nothing at all. */
export function RunMapView({ runId, title = "The partition", quietIfNone = false }: { runId: Id; title?: string; quietIfNone?: boolean }) {
  const cells = useQuery({ queryKey: ["run-map", runId], queryFn: () => getRunMap(runId), retry: false });
  const zones = useQuery({
    queryKey: ["run-map", runId, "zones"],
    queryFn: () => getRunMap(runId, true),
    retry: false,
    enabled: cells.isSuccess,
  });
  const canvas = useRef<HTMLCanvasElement>(null);
  const { basemaps, chosen, choose } = useBasemaps();
  const [exportFailed, setExportFailed] = useState(false);
  const features = cells.data?.features ?? [];
  const groups = [...new Set(features.map((f) => String(f.properties.group)))].sort();
  const colour = (group: unknown) => ZONE_COLOURS[groups.indexOf(String(group)) % ZONE_COLOURS.length];
  // A nested partition: within a zone's colour, its sub-zones take turns
  // at full and lighter shade, so each sub-zone reads as its own piece.
  const subgroups = [...new Set(features.map((f) => `${String(f.properties.group)}|${String(f.properties.subgroup)}`))].sort();
  const shade = (f: { properties: Record<string, unknown> }) => {
    if (f.properties.subgroup == null) return 0.8;
    const mine = `${String(f.properties.group)}|${String(f.properties.subgroup)}`;
    const siblings = subgroups.filter((key) => key.startsWith(`${String(f.properties.group)}|`));
    return siblings.indexOf(mine) % 2 === 0 ? 0.9 : 0.5;
  };
  const onCanvas = features.length > SVG_LIMIT;

  useEffect(() => {
    if (!onCanvas || !canvas.current) return;
    const context = canvas.current.getContext("2d");
    if (!context) return;
    const { at } = frameOf(features, chosen);
    context.clearRect(0, 0, WIDTH, HEIGHT);
    for (const feature of features) {
      context.fillStyle = colour(feature.properties.group);
      context.globalAlpha = shade(feature);
      for (const rings of polygons(feature)) {
        context.beginPath();
        for (const ring of rings)
          ring.forEach((p, i) => {
            const [x, y] = at(p);
            if (i) context.lineTo(x, y);
            else context.moveTo(x, y);
          });
        context.fill("evenodd");
      }
    }
  });

  if (cells.isLoading) return quietIfNone ? null : <SkeletonCard title={title} rows={6} />;
  if (cells.isError) {
    if (notSpatial(cells.error) && quietIfNone) return null;
    return (
      <Card title={title} tone="warn">
        <p>{notSpatial(cells.error) ? "This run has no map to draw." : "The map could not be loaded."}</p>
      </Card>
    );
  }
  const frame = features.length ? frameOf(features, chosen) : null;
  const at = frame?.at ?? null;
  const onImagery = (frame?.tiles.length ?? 0) > 0;
  const totals = zones.data?.features ?? [];
  const columns = [...new Set(totals.flatMap((z) => Object.keys(z.properties)))].filter((k) => !HIDDEN.has(k));
  const label = `${features.length} cells in ${groups.length} ${groups.length === 1 ? "group" : "groups"}`;

  async function exportZones() {
    setExportFailed(false);
    try {
      download(`run-${runId}-zones.geojson`, await getRunMap(runId, true));
    } catch {
      setExportFailed(true);
    }
  }

  return (
    <Card title={title}>
      {basemaps.length > 0 && (
        <label className="mb-1 flex items-center gap-2 text-xs text-slate-600">
          Background
          <select
            className="rounded border border-slate-300 px-1 py-0.5 text-xs"
            value={chosen?.id ?? NO_BASEMAP}
            onChange={(event) => choose(event.target.value)}
          >
            <option value={NO_BASEMAP}>none</option>
            {basemaps.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="relative w-full max-w-xl" style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}>
      {onImagery && chosen && frame && (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="absolute inset-0 h-full w-full" aria-hidden="true" data-testid="basemap">
          {frame.tiles.map((tile) => (
            <image
              key={`${tile.z}/${tile.x}/${tile.y}/${tile.left}`}
              href={tileUrl(chosen.url, tile)}
              x={tile.left}
              y={tile.top}
              width={tile.size + 0.5}
              height={tile.size + 0.5}
              preserveAspectRatio="none"
            />
          ))}
        </svg>
      )}
      {onCanvas ? (
        <canvas ref={canvas} width={WIDTH} height={HEIGHT} className="absolute inset-0 h-full w-full" role="img" aria-label={label} />
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="absolute inset-0 h-full w-full" role="img" aria-label={label}>
          {at &&
            features.map((f) => (
              <path
                key={String(f.properties.key)}
                d={pathOf(f, at)}
                fill={colour(f.properties.group)}
                fillOpacity={onImagery ? shade(f) * 0.7 : shade(f)}
                fillRule="evenodd"
                stroke="white"
                strokeWidth={0.6}
              >
                <title>
                  {`${String(f.properties.key)}: ${String(f.properties.group ?? "no group")}` +
                    (f.properties.subgroup ? ` / ${String(f.properties.subgroup)}` : "")}
                </title>
              </path>
            ))}
        </svg>
      )}
      </div>
      {onImagery && chosen?.attribution && <p className="mt-1 text-[10px] text-slate-500">{chosen.attribution}</p>}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <caption className="sr-only">Totals by group</caption>
          <thead>
            <tr className="text-slate-600">
              <th className="text-left font-medium">Group</th>
              <th className="text-right font-medium">Cells</th>
              {columns.map((k) => (
                <th key={k} className="text-right font-medium">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {totals.map((z) => (
              <tr key={`${String(z.properties.group)}-${String(z.properties.subgroup)}`}>
                <td>
                  <span
                    aria-hidden="true"
                    className="mr-1 inline-block h-2 w-2 rounded-sm"
                    style={{ background: colour(z.properties.group), opacity: shade(z) }}
                  />
                  {String(z.properties.group ?? "no group")}
                  {z.properties.subgroup ? ` / ${String(z.properties.subgroup)}` : ""}
                </td>
                <td className="text-right">{formatNumber(z.properties.cells)}</td>
                {columns.map((k) => (
                  <td key={k} className="text-right">
                    {formatNumber(z.properties[k])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" onClick={() => void exportZones()} className="mt-2 text-sm text-blue-700 underline">
        Export the zones (GeoJSON)
      </button>
      {exportFailed && (
        <p role="alert" className="text-sm text-red-700">
          The zones could not be exported.
        </p>
      )}
    </Card>
  );
}

export default function SpatialMap({ record }: GenUIProps) {
  return <RunMapView runId={Number(record.props.runId)} title={String(record.props.title ?? "The partition")} />;
}

export function SpatialMapSkeleton({ record }: GenUIProps) {
  return <SkeletonCard title={String(record.props.title ?? "The partition")} rows={6} />;
}
