/**
 * Map data: the domain's GIS layers, imported from CAD drawings. Each import
 * keeps the drawing's layers, colours, text and blocks, placed on the Earth
 * with the coordinate system chosen for it.
 */
import { Link, useSearchParams } from "react-router-dom";
import { Database, FileUp, Layers, Wand2 } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getDataset, makeRecords, proposeRecords, useDatasets } from "../api/gis";
import { formatApiError } from "../api/errors";
import { useEntityTypes } from "../api/v1";
import MeasureFromMap from "../components/MeasureFromMap";
import DeriveLayer from "../components/map/DeriveLayer";
import AutoRecords from "../components/map/AutoRecords";
import LoadFailure from "../components/LoadFailure";
import Skeleton from "../components/Skeleton";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { relativeTime } from "../lib/relativeTime";

export default function MapData() {
  useDocumentTitle("Map data");
  const { domainId } = useDomain();
  const list = useDatasets(domainId);
  const kinds = useEntityTypes(domainId, { limit: 500 });
  const placed = (kinds.data?.items ?? []).filter((t) => t.attributes.some((a) => a.data_type === "geometry"));
  const { can } = useCapabilities();
  // `?records=1` (the "Map to records" link on a drawing's page) opens the mapping straight away.
  const [search, setSearch] = useSearchParams();
  const [mapping, setMappingOpen] = useState(search.get("records") === "1");
  const setMapping = (value: boolean) => {
    setMappingOpen(value);
    if (!value && search.has("records")) {
      search.delete("records");
      setSearch(search, { replace: true });
    }
  };
  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="mb-1 text-lg font-semibold text-slate-900">Map data</h1>
            <p className="max-w-2xl text-sm text-slate-500">
              CAD drawings (DXF) and GIS files (GeoJSON, KML/KMZ, GPX, Shapefile, GeoPackage, CSV) brought onto the map as
              layers: points, lines, areas, text and attributes, placed on the ground with their coordinate system and
              checked over imagery before they are stored.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
          {can("domain.edit") && (list.data?.items.length ?? 0) > 0 && (
            <button type="button" onClick={() => setMapping(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">
              <Wand2 className="h-4 w-4" aria-hidden /> Map to records
            </button>
          )}
          {can("domain.edit") && (
            <Link to={`/domains/${domainId}/map-data/import`}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
              <FileUp className="h-4 w-4" aria-hidden /> Import map data (DXF, GeoJSON, KML, Shapefile…)
            </Link>
          )}
          </div>
        </header>
      </div>
      {mapping && <AutoRecords domainId={domainId} onClose={() => setMapping(false)} />}
      {list.isLoading ? <Skeleton /> : list.isError ? (
        <LoadFailure subject="The map data" error={list.error} retry={() => void list.refetch()} />
      ) : (
        <>
          {list.data!.items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
              No map data in this domain yet.
            </p>
          ) : (
            <ul className="space-y-3">
              {list.data!.items.map((d) => (
                <li key={d.id} className="rounded-lg border border-slate-200 bg-white p-4" data-testid="dataset">
                  <div className="flex items-start gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sky-50 text-sky-700" aria-hidden>
                      <Layers className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <Link to={`/domains/${domainId}/map-data/${d.id}`} className="font-semibold text-slate-900 hover:underline">{d.name}</Link>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {d.source.filename} · {d.layers} layers · {(d.stats.features ?? 0).toLocaleString()} features ·{" "}
                        {d.placement.kind === "epsg" ? d.placement.name ?? `EPSG:${d.placement.code}` : "local coordinates"} ·
                        {" "}imported {relativeTime(d.created_at)}
                      </p>
                    </div>
                    {can("domain.edit") && <QuickRecords domainId={domainId} datasetId={d.id} />}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {can("domain.edit") && list.data!.items.length > 0 && (placed.length > 0 ? (
            <div className="space-y-3">
              <MeasureFromMap domainId={domainId} entityTypes={kinds.data?.items ?? []} />
              <DeriveLayer domainId={domainId} title="Make a map layer: rings round records, the places each reaches, the places none reaches" />
            </div>
          ) : (
            <p className="rounded-md border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
              Next: open a layer and choose <strong>Use in models</strong> to make its features records. Then distances,
              what is within reach and which area each place is in can be computed here, for a model to read.
            </p>
          ))}
          <p className="flex items-center gap-1.5 text-xs text-slate-500">
            <Database className="h-3.5 w-3.5" aria-hidden />
            {list.data!.postgis
              ? "Stored in PostGIS: a GIS desktop such as QGIS can read the gis_feature table of this database as a layer."
              : "Stored as GeoJSON in the database. With PostGIS on the database server, features also get a spatial geometry and index."}
          </p>
        </>
      )}
    </div>
  );
}

/**
 * Records from a file in one click (enhancement after the user trial: four files meant four trips through
 * "Use in models"): every layer with features, the suggested kind name and key. A kind of that name
 * already there is never added to here -- that choice is made on the file's own page.
 */
export function QuickRecords({ domainId, datasetId }: { domainId: number; datasetId: number }) {
  const client = useQueryClient();
  const [state, setState] = useState<{ busy?: boolean; made?: { type: string; id: number; n: number }; exists?: string; error?: string }>({});
  if (state.made) {
    return (
      <Link className="shrink-0 text-xs text-emerald-800 underline" to={`/domains/${domainId}/data/records?type=${state.made.id}`}>
        ✓ {state.made.n} {state.made.type.replace(/_/g, " ")} records
      </Link>
    );
  }
  if (state.exists) {
    return (
      <Link className="shrink-0 text-xs text-amber-800 underline" to={`/domains/${domainId}/map-data/${datasetId}`}>
        A kind “{state.exists}” exists: choose on the file’s page
      </Link>
    );
  }
  return (
    <span className="flex shrink-0 flex-col items-end gap-1">
      <button type="button" disabled={state.busy} className="rounded-md border border-blue-600 px-2 py-1 text-xs font-medium text-blue-700 disabled:opacity-60"
        onClick={async () => {
          setState({ busy: true });
          try {
            const dataset = await getDataset(datasetId);
            const layers = dataset.layers.filter((l) => l.feature_count > 0).map((l) => l.name);
            const plan = await proposeRecords(datasetId, layers);
            if (plan.exists) return setState({ exists: plan.name });
            const made = await makeRecords(datasetId, layers, plan);
            // Only what records change: refreshing everything re-mounts the page and loses this row's answer.
            await client.invalidateQueries({ queryKey: ["v1", "entity-types"] });
            setState({ made: { type: made.type, id: made.entity_type_id, n: made.made } });
          } catch (e) {
            setState({ error: formatApiError(e) });
          }
        }}>
        {state.busy ? "Making…" : "Make records"}
      </button>
      {state.error && <span role="alert" className="text-xs text-red-700">{state.error}</span>}
    </span>
  );
}
