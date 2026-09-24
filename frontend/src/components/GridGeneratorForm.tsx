/**
 * Make a grid over a boundary (GIS 3): which shape to cover, square or hex
 * cells of a width in metres, and an optional CSV of points summed into the
 * cells. The server writes the cells and their adjacency in one step; a grid
 * already in use is replaced only after saying what that replaces.
 */
import { useId, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { useEntitiesOfTypes, useMakeGrid, useSettings, type EntityType, type GridReport, type Id } from "../api/v1";
import GeometryPreview from "./GeometryPreview";

/** `lon,lat,<column>...` rows into point records; a header line is required. */
export function parsePointsCsv(textIn: string): { rows: Record<string, number>[]; problem: string | null } {
  const lines = textIn.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return { rows: [], problem: null };
  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  if (header[0] !== "lon" || header[1] !== "lat") {
    return { rows: [], problem: 'The first line names the columns and starts "lon,lat".' };
  }
  const rows: Record<string, number>[] = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cells = lines[i].split(",").map((c) => c.trim());
    const row: Record<string, number> = {};
    for (let c = 0; c < header.length; c += 1) {
      const value = Number(cells[c]);
      if (cells[c] === undefined || cells[c] === "" || !Number.isFinite(value)) {
        return { rows: [], problem: `Line ${i + 1}: "${header[c]}" is not a number.` };
      }
      row[header[c]] = value;
    }
    rows.push(row);
  }
  return { rows, problem: null };
}

function refusalOf(error: unknown): { cells: number; scenarios: number[] } | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  try {
    const detail = JSON.parse(error.message)?.detail;
    return typeof detail?.cells === "number" ? { cells: detail.cells, scenarios: detail.scenarios ?? [] } : null;
  } catch {
    return null;
  }
}

export default function GridGeneratorForm({ domainId, entityTypes }: { domainId: Id; entityTypes: EntityType[] }) {
  const ids = { boundary: useId(), shape: useId(), size: useId(), name: useId(), keep: useId(), csv: useId() };
  const shaped = useMemo(
    () => entityTypes.filter((t) => (t.attributes ?? []).some((a) => a.data_type === "geometry")),
    [entityTypes]
  );
  const candidates = useEntitiesOfTypes(shaped.map((t) => t.id));
  const boundaries = candidates.items.filter((e) => {
    const type = shaped.find((t) => String(t.id) === String(e.entity_type_id));
    const shape = (type?.attributes ?? []).find((a) => a.data_type === "geometry" && e.attrs?.[a.name]);
    const value = shape ? (e.attrs[shape.name] as { type?: string }) : null;
    return value && value.type !== "Point";
  });
  const make = useMakeGrid();
  const [boundary, setBoundary] = useState<string>("");
  const [shape, setShape] = useState<"hex" | "square">("hex");
  const [size, setSize] = useState("500");
  const [name, setName] = useState("cell");
  const [keep, setKeep] = useState<"centre" | "overlap">("centre");
  const [csv, setCsv] = useState("");
  const [report, setReport] = useState<GridReport | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [inUse, setInUse] = useState<{ cells: number; scenarios: number[] } | null>(null);
  const [elevation, setElevation] = useState(false);
  // Elevation is offered only when a tile index is named (GIS 10); the
  // server finds the terrain tileset in it.
  const settings = useSettings({ domainId });
  const tilesIndex = String(settings.data?.items?.find((item) => item.key === "spatial.tiles_index")?.value ?? "").trim();

  const chosen = boundaries.find((e) => String(e.id) === boundary) ?? boundaries[0];
  const points = parsePointsCsv(csv);
  const width = Number(size);

  function submit(replace = false) {
    setFailure(null);
    setReport(null);
    if (!chosen) return;
    make.mutate(
      {
        domainId,
        body: {
          boundary_entity_id: chosen.id,
          shape,
          size_m: width,
          entity_type: name,
          keep,
          layers: points.rows,
          replace,
          ...(elevation && tilesIndex ? { elevation: true } : {}),
        },
      },
      {
        onSuccess: (r) => {
          setReport(r);
          setInUse(null);
        },
        onError: (error: unknown) => {
          const refused = refusalOf(error);
          if (refused) setInUse(refused);
          else setFailure(formatApiError(error));
        },
      }
    );
  }

  if (shaped.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        To make a grid, give an entity type a <em>Shape (GeoJSON)</em> attribute and draw an area on one of its records.
      </p>
    );
  }
  const shapeOf = (entity: typeof chosen) => {
    const type = shaped.find((t) => String(t.id) === String(entity?.entity_type_id));
    const attribute = (type?.attributes ?? []).find((a) => a.data_type === "geometry" && entity?.attrs?.[a.name]);
    return attribute ? entity?.attrs[attribute.name] : null;
  };

  return (
    <form
      className="space-y-3 text-sm"
      aria-label="Make a grid"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={ids.boundary} className="block text-xs text-slate-600">Over</label>
          <select id={ids.boundary} className="rounded border px-2 py-1" value={chosen ? String(chosen.id) : ""}
            onChange={(e) => setBoundary(e.target.value)}>
            {boundaries.length === 0 && <option value="">no record has an area drawn yet</option>}
            {boundaries.map((e) => <option key={String(e.id)} value={String(e.id)}>{e.label || e.key}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.shape} className="block text-xs text-slate-600">Cells</label>
          <select id={ids.shape} className="rounded border px-2 py-1" value={shape} onChange={(e) => setShape(e.target.value as "hex" | "square")}>
            <option value="hex">hexagons</option>
            <option value="square">squares</option>
          </select>
        </div>
        <div>
          <label htmlFor={ids.size} className="block text-xs text-slate-600">Cell width (metres)</label>
          <input id={ids.size} className="w-24 rounded border px-2 py-1" inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} />
        </div>
        <div>
          <label htmlFor={ids.keep} className="block text-xs text-slate-600">Keep a cell when</label>
          <select id={ids.keep} className="rounded border px-2 py-1" value={keep} onChange={(e) => setKeep(e.target.value as "centre" | "overlap")}>
            <option value="centre">its centre is inside</option>
            <option value="overlap">any of it is inside</option>
          </select>
        </div>
        <div>
          <label htmlFor={ids.name} className="block text-xs text-slate-600">Entity type of the cells</label>
          <input id={ids.name} className="w-32 rounded border px-2 py-1 font-mono" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {chosen && <GeometryPreview geometry={shapeOf(chosen)} size={64} />}
      </div>
      <div>
        <label htmlFor={ids.csv} className="block text-xs text-slate-600">
          Points to add up per cell (optional CSV: <span className="font-mono">lon,lat,population,...</span>)
        </label>
        <textarea id={ids.csv} rows={4} className="w-full rounded border px-2 py-1 font-mono text-xs" value={csv}
          onChange={(e) => setCsv(e.target.value)} placeholder={"lon,lat,population\n31.24,30.05,1200"} />
        {points.problem ? (
          <p role="alert" className="text-xs text-rose-700">{points.problem}</p>
        ) : (
          points.rows.length > 0 && <p className="text-xs text-slate-500">{points.rows.length} points.</p>
        )}
      </div>
      {tilesIndex && (
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={elevation} onChange={(event) => setElevation(event.target.checked)} />
          Add each cell&rsquo;s elevation and slope, from the terrain tiles
        </label>
      )}
      <button type="submit" className="rounded bg-blue-600 px-3 py-1.5 text-white disabled:opacity-50"
        disabled={!chosen || !(width > 0) || points.problem !== null || make.isPending}>
        {make.isPending ? "Making the grid…" : "Make the grid"}
      </button>
      {inUse && (
        <div role="alert" className="rounded bg-amber-50 p-2 text-amber-900">
          {name} already has {inUse.cells} cells
          {inUse.scenarios.length > 0 ? `, used by scenario${inUse.scenarios.length > 1 ? "s" : ""} ${inUse.scenarios.join(", ")}` : ""}.
          Runs already made keep their frozen data.{" "}
          <button type="button" className="underline" onClick={() => submit(true)}>Replace them</button>
        </div>
      )}
      {failure && <p role="alert" className="text-rose-700">{failure}</p>}
      {report && (
        <p role="status" className="text-slate-700">
          Made {report.cells} cells and {report.edges} adjacencies ({report.dropped} dropped at the boundary).
          {Object.entries(report.layer_outside).map(([column, amount]) => ` ${amount} of ${column} fell outside the grid.`)}
          {report.elevation_range && ` Elevation from ${report.elevation_range[0]} to ${report.elevation_range[1]} m.`}
          {(report.elevation_missing ?? 0) > 0 &&
            ` ${report.elevation_missing} ${report.elevation_missing === 1 ? "cell is" : "cells are"} beyond the terrain tiles and ${report.elevation_missing === 1 ? "has" : "have"} no elevation.`}
        </p>
      )}
    </form>
  );
}
