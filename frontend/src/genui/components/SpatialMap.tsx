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
function projector(features: RunMapFeature[]) {
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
  const k = degrees ? Math.cos((((minY + maxY) / 2) * Math.PI) / 180) : 1;
  const scale = Math.min(WIDTH / ((maxX - minX) * k || 1), HEIGHT / (maxY - minY || 1));
  return ([x, y]: number[]) => [(x - minX) * k * scale, HEIGHT - (y - minY) * scale];
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
  const [exportFailed, setExportFailed] = useState(false);
  const features = cells.data?.features ?? [];
  const groups = [...new Set(features.map((f) => String(f.properties.group)))].sort();
  const colour = (group: unknown) => ZONE_COLOURS[groups.indexOf(String(group)) % ZONE_COLOURS.length];
  const onCanvas = features.length > SVG_LIMIT;

  useEffect(() => {
    if (!onCanvas || !canvas.current) return;
    const context = canvas.current.getContext("2d");
    if (!context) return;
    const at = projector(features);
    context.clearRect(0, 0, WIDTH, HEIGHT);
    for (const feature of features) {
      context.fillStyle = colour(feature.properties.group);
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
  const at = features.length ? projector(features) : null;
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
      {onCanvas ? (
        <canvas ref={canvas} width={WIDTH} height={HEIGHT} className="h-auto w-full" role="img" aria-label={label} />
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full" role="img" aria-label={label}>
          {at &&
            features.map((f) => (
              <path
                key={String(f.properties.key)}
                d={pathOf(f, at)}
                fill={colour(f.properties.group)}
                fillOpacity={0.8}
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
                    style={{ background: colour(z.properties.group) }}
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
