/**
 * A kind of record on the map (improvement plan 1.4): every record of the
 * kind that has a shape, at its place, named by its label or key. Records
 * without a shape are counted, so "is my data where it should be?" can be
 * answered before a model reads it.
 */
import { useEntities, type EntityType } from "../../api/v1";
import GeoMap, { type GeoGeometry, type GeoMark } from "./GeoMap";

const LIMIT = 500;

export function geometryFields(type: EntityType): string[] {
  return type.attributes.filter((a) => a.data_type === "geometry").map((a) => a.name);
}

export default function RecordsMap({ type }: { type: EntityType }) {
  const fields = geometryFields(type);
  const records = useEntities(type.id, { limit: LIMIT, offset: 0 });
  if (records.isLoading) return <p className="text-sm text-slate-600">Loading the places…</p>;
  const items = records.data?.items ?? [];
  const marks: GeoMark[] = [];
  let without = 0;
  for (const e of items) {
    const shape = fields.map((f) => e.attrs?.[f]).find((v) => v && typeof v === "object") as GeoGeometry | undefined;
    if (!shape) { without += 1; continue; }
    marks.push({
      id: String(e.id), geometry: shape, colour: type.colour ?? "#2563eb", size: 5, fill: 0.25,
      title: `${e.label ?? e.key}${e.label ? ` (${e.key})` : ""}`, label: e.label ?? e.key, layer: type.name,
    });
  }
  const total = records.data?.total ?? items.length;
  return (
    <GeoMap marks={marks} caption={[
      `${marks.length} ${type.name} records on the map`,
      without ? `${without} without a shape` : null,
      total > LIMIT ? `the first ${LIMIT} of ${total} shown` : null,
    ].filter(Boolean).join(" · ")} />
  );
}
