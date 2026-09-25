import { useMemo } from "react";
import { useEntities, useEntityTypes, useRelationships, type RelationshipType } from "../api/v1";
import { placeOf } from "./EntityPicture";
import { ShapedView, type Entry } from "./RunViews";

/**
 * A relationship type's links drawn like a yes/no answer over its two ends (queue R17c): a
 * grid of who is linked to whom -- the two ends on the axes -- and, when both ends have a
 * place, the links as lines on a map. Read from the first 500 links and entities.
 */
export default function RelationshipPicture({ type }: { type: RelationshipType }) {
  const links = useRelationships({ relationshipTypeId: type.id, limit: 500 });
  const froms = useEntities(type.from_type_id, { family: true, limit: 500 });
  const tos = useEntities(type.to_type_id, { family: true, limit: 500 });
  const types = useEntityTypes(type.domain_id, { limit: 500 });

  const picture = useMemo(() => {
    const typeOf = (id: number | string) => types.data?.items.find((t) => t.id === id);
    const from = typeOf(type.from_type_id)?.name ?? "from";
    // A type linked to itself (a hierarchy, `adjacent`) still has two ends to draw.
    const to = type.to_type_id === type.from_type_id ? `${from} ` : typeOf(type.to_type_id)?.name ?? "to";
    const ends = [...(froms.data?.items ?? []), ...(tos.data?.items ?? [])];
    const keyOf = new Map(ends.map((e) => [e.id, e.key]));
    const entries: Entry[] = (links.data?.items ?? []).flatMap((l) => {
      const a = keyOf.get(l.from_entity_id), b = keyOf.get(l.to_entity_id);
      return a && b ? [{ index: [a, b], value: null }] : [];
    });
    const placesOf = (items: typeof ends) =>
      Object.fromEntries(items.flatMap((e) => {
        const shape = Object.values(e.attrs ?? {}).find((v) => placeOf(v) !== null);
        const at = shape ? placeOf(shape) : null;
        return at ? [[e.key, at]] : [];
      }));
    const fromPlaces = placesOf(froms.data?.items ?? []), toPlaces = placesOf(tos.data?.items ?? []);
    const places = Object.keys(fromPlaces).length && Object.keys(toPlaces).length ? { [from]: fromPlaces, [to]: toPlaces } : {};
    const order = { [from]: (froms.data?.items ?? []).map((e) => e.key), [to]: (tos.data?.items ?? []).map((e) => e.key) };
    const labels = {
      [from]: Object.fromEntries((froms.data?.items ?? []).filter((e) => e.label).map((e) => [e.key, e.label as string])),
      [to]: Object.fromEntries((tos.data?.items ?? []).filter((e) => e.label).map((e) => [e.key, e.label as string])),
    };
    return { sets: [from, to], entries, places, order, labels };
  }, [links.data, froms.data, tos.data, types.data, type]);

  if (links.isLoading || froms.isLoading || tos.isLoading) return null;
  const total = links.data?.total ?? 0;
  return (
    <ShapedView
      name={type.name}
      shape={{ sets: picture.sets, kind: "binary", roles: {}, hasAmounts: true, located: Object.keys(picture.places) }}
      entries={picture.entries}
      order={picture.order}
      labels={picture.labels}
      places={picture.places}
      count={total > picture.entries.length ? `the first ${picture.entries.length} of ${total} links` : `${total} links`}
      empty="No links yet."
    />
  );
}
