import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import {
  NewRelationshipForm,
  RelationshipList,
  relationshipRows,
} from "../components/RelationshipEditor";
import { INPUT_CLASS } from "../components/attrTypes";
import { formatApiError } from "../api/errors";
import {
  useEntitiesOfTypes,
  useEntityTypes,
  useRelationshipTypes,
  useRelationshipsOfTypes,
  type Entity,
  type EntityType,
  type Id,
  type RelationshipType,
} from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * The domain's relationships: which employee works in which unit, which
 * unit sits under which.
 *
 * `/relationships` returned "Page not found" until now, and the nav
 * offered "Relationship types" and nothing for the rows themselves, so
 * the only route to connecting two entities was one line of grey helper
 * text under the graph toolbar telling you to turn on Connect and drag --
 * on a canvas whose default layout clips the node you need. For a
 * planner, these rows ARE the model; they were the one part of it with no
 * screen at all.
 *
 * Scoped to the sidebar's domain, like every other v1 screen. A domain
 * holds a handful of relationship types, so the page asks for the API's
 * maximum page and does not paginate, exactly as `EntityTypes` and
 * `RelationshipTypes` do.
 */
export default function Relationships() {
  useDocumentTitle("Relationships");
  const { domainId } = useDomain();

  return (
    <div className="max-w-4xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Relationships</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            relationships.
          </p>
          <p className="mt-1">
            No domain yet?{" "}
            <Link to="/public/domain" className="inline-block rounded py-1 text-blue-600 underline">
              Create one on the Domains page
            </Link>
            .
          </p>
        </div>
      ) : (
        <Loaded domainId={domainId} />
      )}
    </div>
  );
}

function Loaded({ domainId }: { domainId: Id }) {
  const entityTypes = useEntityTypes(domainId, { limit: 500 });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500 });
  const types: RelationshipType[] = useMemo(() => relationshipTypes.data?.items ?? [], [relationshipTypes.data]);
  const entityTypeList: EntityType[] = useMemo(() => entityTypes.data?.items ?? [], [entityTypes.data]);

  /** "All", or one type's id. The filter narrows BOTH the table and the
   * requests behind it, so on a large model choosing a type is also how
   * you stop loading the ones you are not looking at. */
  const [typeFilter, setTypeFilter] = useState<Id | "all">("all");
  const shownTypes = useMemo(
    () => (typeFilter === "all" ? types : types.filter((type) => type.id === typeFilter)),
    [types, typeFilter]
  );

  const relationships = useRelationshipsOfTypes(shownTypes.map((type) => type.id));

  /* The entity types that appear as an end of a shown relationship type --
   * which is exactly the set of entities needed to turn `to_entity_id: 4`
   * into "North Depot", and the set the create form's pickers offer. */
  const endTypeIds = useMemo(() => {
    const ids = new Set<Id>();
    for (const type of types) {
      ids.add(type.from_type_id);
      ids.add(type.to_type_id);
    }
    return [...ids].sort((a, b) => a - b);
  }, [types]);
  const entities = useEntitiesOfTypes(endTypeIds);

  const typeById = useMemo(() => new Map(types.map((type) => [type.id, type])), [types]);
  const entityById = useMemo(
    () => new Map(entities.items.map((entity) => [entity.id, entity])),
    [entities.items]
  );
  const entitiesByType = useMemo(() => {
    const grouped = new Map<Id, Entity[]>();
    for (const entity of entities.items) {
      const list = grouped.get(entity.entity_type_id);
      if (list) list.push(entity);
      else grouped.set(entity.entity_type_id, [entity]);
    }
    return grouped;
  }, [entities.items]);
  const entityTypeNames = useMemo(
    () => new Map(entityTypeList.map((type) => [type.id, type.name])),
    [entityTypeList]
  );

  const paused = relationshipTypes.fetchStatus === "paused" && !relationshipTypes.data;
  if (paused) return <OfflineNotice subject="The relationship list" />;

  const loadError = relationshipTypes.error ?? entityTypes.error ?? relationships.error ?? entities.error;
  if (loadError && !relationshipTypes.data) {
    return (
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <p className="text-sm text-red-600">{formatApiError(loadError)}</p>
        <button
          type="button"
          onClick={() => relationshipTypes.refetch()}
          className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
        >
          Retry
        </button>
      </div>
    );
  }

  if (relationshipTypes.isLoading) return <Skeleton rows={3} cols={4} />;

  if (types.length === 0) {
    return (
      <p className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        This domain has no relationship types yet, and a relationship is always of some type.{" "}
        <Link to="/relationship-types" className="inline-block rounded py-1 text-blue-600 underline">
          Define the first one
        </Link>
        .
      </p>
    );
  }

  const rows = relationshipRows(relationships.items, typeById, entityById);

  return (
    <>
      <div className="mb-4 max-w-sm">
        <label htmlFor="relationship-type-filter" className="block text-sm font-medium text-slate-700">
          Show
        </label>
        <select
          id="relationship-type-filter"
          className={INPUT_CLASS}
          value={typeFilter === "all" ? "all" : String(typeFilter)}
          onChange={(event) =>
            setTypeFilter(event.target.value === "all" ? "all" : Number(event.target.value))
          }
          data-testid="relationship-filter"
        >
          <option value="all">All relationship types</option>
          {types.map((type) => (
            <option key={type.id} value={type.id}>
              {type.name} ({entityTypeNames.get(type.from_type_id) ?? `#${type.from_type_id}`} →{" "}
              {entityTypeNames.get(type.to_type_id) ?? `#${type.to_type_id}`})
            </option>
          ))}
        </select>
      </div>

      {relationships.isLoading || entities.isLoading ? (
        <Skeleton rows={3} cols={4} />
      ) : (
        <>
          <p className="mb-2 text-sm text-slate-600" data-testid="relationship-count">
            {(relationships.total ?? rows.length) > rows.length
              ? `The first ${rows.length.toLocaleString("en-US")} of ${(relationships.total ?? 0).toLocaleString("en-US")} relationships`
              : rows.length === 1 ? "1 relationship" : `${rows.length.toLocaleString("en-US")} relationships`}
            {typeFilter === "all" ? " in this domain" : ""}.
          </p>
          <RelationshipList
            rows={rows}
            caption="Relationships"
            emptyNote={
              typeFilter === "all"
                ? "No relationships in this domain yet."
                : "No relationships of this type yet."
            }
            entityHref={(id) => `/entities/${id}`}
            truncated={relationships.truncated || entities.truncated}
          />
        </>
      )}

      <NewRelationshipForm
        types={types}
        entitiesByType={entitiesByType}
        entityTypeNames={entityTypeNames}
        heading="New relationship"
      />
    </>
  );
}
