import { useMemo } from "react";
import OfflineNotice from "./OfflineNotice";
import Skeleton from "./Skeleton";
import { NewRelationshipForm, RelationshipList, relationshipRows } from "./RelationshipEditor";
import { formatApiError } from "../api/errors";
import {
  useEntitiesOfTypes,
  useEntityTypes,
  useRelationshipTypes,
  useRelationships,
  type Entity,
  type EntityType,
  type Id,
} from "../api/v1";

/**
 * One entity's relationships, both directions.
 *
 * This is the fact an entity's page never showed: that Ahmed works in
 * North Depot, that North Depot sits under North Region. The page's own
 * delete confirmation already counted these -- "Its relationships and any
 * parameter values indexed by it go with it" -- about things the product
 * had never let the reader see.
 *
 * Both directions in ONE table, in each row's own direction, with this
 * entity marked: an employee's `works_in` row and a unit's incoming
 * `works_in` rows are the same relationships seen from opposite ends, and
 * splitting them into "outgoing" and "incoming" would make the reader
 * learn a word for a distinction the sentence already makes.
 *
 * Two list requests, `from_entity_id=` and `to_entity_id=`, because that
 * is what the API filters by and there is no "either end" filter. An edge
 * from an entity to itself would appear in both, so the rows are merged
 * by id rather than concatenated -- the hierarchy trigger refuses such a
 * row, but nothing stops a non-hierarchy type holding one.
 */
export default function EntityRelationships({
  entity,
  entityType,
}: {
  entity: Entity;
  entityType: EntityType;
}) {
  const outgoing = useRelationships({ fromEntityId: entity.id, limit: 500 });
  const incoming = useRelationships({ toEntityId: entity.id, limit: 500 });
  const relationshipTypes = useRelationshipTypes(entityType.domain_id, { limit: 500 });
  const entityTypes = useEntityTypes(entityType.domain_id, { limit: 500 });

  const types = useMemo(() => relationshipTypes.data?.items ?? [], [relationshipTypes.data]);
  const typeById = useMemo(() => new Map(types.map((type) => [type.id, type])), [types]);

  /* Only the entity types that can appear at the other end of one of THIS
   * entity's relationships -- for the seeded demo that is one or two
   * lists, not the whole domain. */
  const endTypeIds = useMemo(() => {
    const ids = new Set<Id>();
    for (const type of types) {
      if (type.from_type_id === entityType.id) ids.add(type.to_type_id);
      if (type.to_type_id === entityType.id) ids.add(type.from_type_id);
    }
    return [...ids].sort((a, b) => a - b);
  }, [types, entityType.id]);
  const others = useEntitiesOfTypes(endTypeIds);

  const entityById = useMemo(() => {
    const map = new Map<Id, Entity>(others.items.map((row) => [row.id, row]));
    // This entity is one end of every row here and is not necessarily in
    // the lists above (its own type need not be at any far end).
    map.set(entity.id, entity);
    return map;
  }, [others.items, entity]);

  const entitiesByType = useMemo(() => {
    const grouped = new Map<Id, Entity[]>();
    for (const row of others.items) {
      const list = grouped.get(row.entity_type_id);
      if (list) list.push(row);
      else grouped.set(row.entity_type_id, [row]);
    }
    return grouped;
  }, [others.items]);

  const entityTypeNames = useMemo(
    () => new Map((entityTypes.data?.items ?? []).map((type) => [type.id, type.name])),
    [entityTypes.data]
  );

  const merged = useMemo(() => {
    const byId = new Map(
      [...(outgoing.data?.items ?? []), ...(incoming.data?.items ?? [])].map((row) => [row.id, row])
    );
    return [...byId.values()].sort((a, b) => a.id - b.id);
  }, [outgoing.data, incoming.data]);

  const paused =
    (outgoing.fetchStatus === "paused" && !outgoing.data) || (incoming.fetchStatus === "paused" && !incoming.data);

  const error = outgoing.error ?? incoming.error ?? relationshipTypes.error ?? others.error;

  return (
    <section aria-labelledby="entity-relationships-heading" className="space-y-4">
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <h2 id="entity-relationships-heading" className="mb-1 text-base font-semibold text-slate-900">
          Relationships
        </h2>
        <p className="mb-3 text-sm text-slate-600">
          Every relationship this entity takes part in, whichever end it is on. Deleting the entity deletes these
          too.
        </p>
        {paused ? (
          <OfflineNotice subject="This entity's relationships" />
        ) : error && !outgoing.data ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-red-600">{formatApiError(error)}</p>
            <button
              type="button"
              onClick={() => {
                outgoing.refetch();
                incoming.refetch();
              }}
              className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
            >
              Retry
            </button>
          </div>
        ) : outgoing.isLoading || incoming.isLoading ? (
          <Skeleton rows={2} cols={4} />
        ) : (
          <RelationshipList
            rows={relationshipRows(merged, typeById, entityById)}
            caption={`Relationships of ${entity.label ?? entity.key}`}
            emptyNote="This entity is not connected to anything yet. Add the first relationship below."
            subjectId={entity.id}
            entityHref={(id) => `/entities/${id}`}
            truncated={others.truncated}
          />
        )}
      </div>
      {relationshipTypes.data && (
        <NewRelationshipForm
          types={types}
          entitiesByType={entitiesByType}
          entityTypeNames={entityTypeNames}
          subject={{
            id: entity.id,
            entityTypeId: entityType.id,
            label: entity.label && entity.label.trim() !== "" ? entity.label : entity.key,
          }}
          heading="Add a relationship"
        />
      )}
    </section>
  );
}
