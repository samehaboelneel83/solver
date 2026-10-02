/**
 * Map data: the domain's GIS layers, imported from CAD drawings. Each import
 * keeps the drawing's layers, colours, text and blocks, placed on the Earth
 * with the coordinate system chosen for it.
 */
import { Link } from "react-router-dom";
import { Database, FileUp, Layers } from "lucide-react";
import { useDatasets } from "../api/gis";
import { useEntityTypes } from "../api/v1";
import MeasureFromMap from "../components/MeasureFromMap";
import LoadFailure from "../components/LoadFailure";
import Skeleton from "../components/Skeleton";
import MapDataTabs from "../components/map/MapDataTabs";
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
  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <MapDataTabs domainId={domainId} />
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="mb-1 text-lg font-semibold text-slate-900">Map data</h1>
            <p className="max-w-2xl text-sm text-slate-500">
              CAD drawings (DXF) and GIS files (GeoJSON, KML/KMZ, GPX, Shapefile, GeoPackage, CSV) brought onto the map as
              layers: points, lines, areas, text and attributes, placed on the ground with their coordinate system and
              checked over imagery before they are stored.
            </p>
          </div>
          {can("domain.edit") && (
            <Link to={`/domains/${domainId}/map-data/import`}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
              <FileUp className="h-4 w-4" aria-hidden /> Import map data (DXF, GeoJSON, KML, Shapefile…)
            </Link>
          )}
        </header>
      </div>
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
                  </div>
                </li>
              ))}
            </ul>
          )}
          {can("domain.edit") && list.data!.items.length > 0 && (placed.length > 0 ? (
            <MeasureFromMap domainId={domainId} entityTypes={kinds.data?.items ?? []} />
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
