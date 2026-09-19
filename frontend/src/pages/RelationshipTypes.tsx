import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import RelationshipTypeFields, {
  RELATIONSHIP_TYPE_FIELDS,
  type RelationshipTypeDraft,
} from "../components/RelationshipTypeFields";
import { ErrorSummary, nameProblem, serverFieldErrors, useFieldErrors, type FieldErrors } from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import {
  useCreateRelationshipType,
  useEntityTypes,
  useRelationshipTypes,
  type EntityType,
  type Id,
  type RelationshipType,
} from "../api/v1";
import { CARDINALITY_LABEL } from "../lib/cardinality";
import { typeColour } from "../lib/colour";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * The selected domain's relationship types -- the other half of its
 * schema. Each row opens its editor; new ones are created here.
 *
 * Relationship types have had an API since Task 7 and have been *drawn* by
 * the graph's types view since Task 14b, but until Task 14f there was no
 * way to make one without curl (Ruling 35).
 *
 * A domain holds a handful of these, so the page asks for the API's
 * maximum page (500) and does not paginate, exactly as `EntityTypes` does.
 */
export default function RelationshipTypes() {
  useDocumentTitle("Relationship types");
  const { domainId } = useDomain();

  return (
    <div className="max-w-4xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Relationship types</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            relationship types.
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
  // Both the list (to name each end) and the form (to offer the ends)
  // need the domain's entity types, so they are fetched once here.
  const entityTypes = useEntityTypes(domainId, { limit: 500 });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500 });
  const types = entityTypes.data?.items ?? [];

  return (
    <>
      <TypeList query={relationshipTypes} entityTypes={types} />
      {entityTypes.isLoading ? null : types.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          A relationship type joins two entity types, so this domain needs at least one entity type first.{" "}
          <Link to="/entity-types" className="inline-block rounded py-1 text-blue-600 underline">
            Create an entity type
          </Link>
          .
        </p>
      ) : (
        <CreateTypeForm domainId={domainId} entityTypes={types} />
      )}
    </>
  );
}

/** Entity type names by id: the list stores ids, but an id tells a reader
 * nothing. An id with no matching type (deleted underneath, or a stale
 * cache) is shown as `#id` rather than blank. */
function nameOf(entityTypes: EntityType[], id: Id): string {
  return entityTypes.find((type) => type.id === id)?.name ?? `#${id}`;
}

function TypeList({
  query,
  entityTypes,
}: {
  query: ReturnType<typeof useRelationshipTypes>;
  entityTypes: EntityType[];
}) {
  const { data, error, isLoading, refetch, fetchStatus } = query;

  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="The relationship type list" />;
  if (isLoading) return <Skeleton rows={3} cols={4} />;
  if (error && !data) {
    return (
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <p className="text-sm text-red-600">{formatApiError(error)}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
        >
          Retry
        </button>
      </div>
    );
  }

  const types: RelationshipType[] = data?.items ?? [];
  if (types.length === 0) {
    return (
      <p className="mb-6 text-sm text-slate-600">
        No relationship types in this domain yet. Create the first one below.
      </p>
    );
  }

  return (
    <div className="mb-6 overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm" aria-label="Relationship types">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">
              Name
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              From
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              To
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Cardinality
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Hierarchy
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Colour
            </th>
          </tr>
        </thead>
        <tbody>
          {types.map((type) => (
            <tr key={type.id} className="border-b border-slate-100 last:border-0">
              <th scope="row" className="px-3 py-2 font-normal">
                <Link
                  to={`/relationship-types/${type.id}`}
                  className="inline-block rounded py-1 font-mono text-blue-600 underline"
                >
                  {type.name}
                </Link>
              </th>
              <td className="px-3 py-2 font-mono text-xs text-slate-700">{nameOf(entityTypes, type.from_type_id)}</td>
              <td className="px-3 py-2 font-mono text-xs text-slate-700">{nameOf(entityTypes, type.to_type_id)}</td>
              <td className="px-3 py-2 text-slate-700">
                {CARDINALITY_LABEL[type.cardinality] ?? type.cardinality}
              </td>
              <td className="px-3 py-2 text-slate-700">{type.is_hierarchy ? "Yes" : "No"}</td>
              <td className="px-3 py-2 text-slate-700">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="inline-block h-4 w-4 rounded border border-slate-300"
                    style={{ backgroundColor: typeColour({ id: String(type.id), colour: type.colour }) }}
                    data-testid={`reltype-swatch-${type.name}`}
                  />
                  {/* Decorative swatch, readable text -- Task 14b's rule. */}
                  <span className="font-mono text-xs">{type.colour ?? "automatic"}</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function emptyDraft(entityTypes: EntityType[]): RelationshipTypeDraft {
  const first = entityTypes[0]?.id ?? null;
  return {
    name: "",
    // Pre-selecting the first type on both ends is a convenience, not the
    // hierarchy constraint: the cardinality below is the column default,
    // so the draft starts as an ordinary many-to-many edge.
    from_type_id: first,
    to_type_id: first,
    cardinality: "many_to_many",
    is_hierarchy: false,
    colour: null,
  };
}

function CreateTypeForm({ domainId, entityTypes }: { domainId: Id; entityTypes: EntityType[] }) {
  const [draft, setDraft] = useState<RelationshipTypeDraft>(() => emptyDraft(entityTypes));
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const createType = useCreateRelationshipType();
  const toast = useToast();
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    const problems: FieldErrors = {};
    const problem = nameProblem(draft.name, false);
    if (problem) problems.name = problem;
    if (draft.from_type_id === null) problems.from_type_id = "From entity type: choose an entity type.";
    if (draft.to_type_id === null) problems.to_type_id = "To entity type: choose an entity type.";
    replace(problems);
    if (Object.keys(problems).length > 0) return;
    try {
      const created = await createType.mutateAsync({
        domain_id: domainId,
        name: draft.name,
        from_type_id: draft.from_type_id as Id,
        to_type_id: draft.to_type_id as Id,
        cardinality: draft.cardinality,
        is_hierarchy: draft.is_hierarchy,
        colour: draft.colour,
      });
      toast.success(`Relationship type "${created.name}" created`);
      navigate(`/relationship-types/${created.id}`);
    } catch (err) {
      const result = serverFieldErrors(err, RELATIONSHIP_TYPE_FIELDS, "relationship type");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section
      aria-labelledby="new-relationship-type-heading"
      className="rounded-md border border-slate-200 bg-white p-4"
    >
      <h2 id="new-relationship-type-heading" className="mb-3 text-base font-semibold text-slate-900">
        New relationship type
      </h2>
      <form aria-label="New relationship type" onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={RELATIONSHIP_TYPE_FIELDS} summaryRef={summaryRef} />
        {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
        <RelationshipTypeFields
          draft={draft}
          onChange={(next) => {
            setDraft(next);
            // Clear a name error as soon as the name is edited, the way
            // `EntityTypes` does -- a stale red field is its own bug.
            if (errors.name && next.name !== draft.name) {
              const { name: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
          entityTypes={entityTypes}
          errors={errors}
          fallbackKey={draft.name}
        />
        <button
          type="submit"
          disabled={createType.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {createType.isPending ? "Saving…" : "Create relationship type"}
        </button>
      </form>
    </section>
  );
}
