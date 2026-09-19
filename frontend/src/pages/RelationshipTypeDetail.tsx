import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import RelationshipTypeFields, {
  RELATIONSHIP_TYPE_FIELDS,
  draftFromType,
  type RelationshipTypeDraft,
} from "../components/RelationshipTypeFields";
import { ErrorSummary, nameProblem, serverFieldErrors, useFieldErrors, type FieldErrors } from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import { useToast } from "../components/ToastProvider";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import {
  useDeleteRelationshipType,
  useEntityTypes,
  useRelationshipType,
  useRelationships,
  useUpdateRelationshipType,
  type Id,
  type RelationshipType,
} from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

const BACK_LINK = "inline-block rounded py-1 text-sm text-blue-600 underline";

/** One relationship type: its name, its two ends, its cardinality, whether
 * it is a hierarchy, and its colour -- edited together, then deleted here
 * if it is no longer wanted. */
export default function RelationshipTypeDetail() {
  const { id: rawId } = useParams();
  const id = parseRouteId(rawId);
  const { data, error, isError, refetch, fetchStatus } = useRelationshipType(id);
  useDocumentTitle(data ? `Relationship type ${data.name}` : "Relationship type");

  if (id === null || (isError && error instanceof ApiError && error.status === 404)) {
    return (
      <div>
        <p className="text-sm text-slate-600">Relationship type not found.</p>
        <Link to="/relationship-types" className={BACK_LINK}>
          Back to relationship types
        </Link>
      </div>
    );
  }
  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="This relationship type" />;
  if (isError && !data) {
    return (
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <p className="text-sm text-red-600">{formatApiError(error)}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            Retry
          </button>
        </div>
        <Link to="/relationship-types" className={BACK_LINK}>
          Back to relationship types
        </Link>
      </div>
    );
  }
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;

  // Keyed on the row, so switching types re-seeds the form rather than
  // editing one type's draft into another's -- `EntityTypeDetail`'s rule.
  return <Editor key={data.id} type={data} />;
}

function Editor({ type }: { type: RelationshipType }) {
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <nav aria-label="Breadcrumb" className="mb-2 text-sm">
          <Link to="/relationship-types" className={BACK_LINK}>
            Relationship types
          </Link>
        </nav>
        <h1 className="text-lg font-semibold text-slate-900">
          <span className="sr-only">Relationship type </span>
          <span className="font-mono">{type.name}</span>
        </h1>
      </div>
      <TypeForm type={type} />
      <DeleteType type={type} />
    </div>
  );
}

function TypeForm({ type }: { type: RelationshipType }) {
  const [draft, setDraft] = useState<RelationshipTypeDraft>(() => draftFromType(type));
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  // The type's own domain, not the sidebar's selection: this page is
  // reachable by URL, and rule 3 scopes the ends to the *row's* domain.
  const entityTypes = useEntityTypes(type.domain_id, { limit: 500 });
  const updateType = useUpdateRelationshipType();
  const toast = useToast();

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
      await updateType.mutateAsync({
        id: type.id,
        body: {
          name: draft.name,
          from_type_id: draft.from_type_id as Id,
          to_type_id: draft.to_type_id as Id,
          cardinality: draft.cardinality,
          is_hierarchy: draft.is_hierarchy,
          colour: draft.colour,
        },
      });
      toast.success("Relationship type saved");
    } catch (err) {
      const result = serverFieldErrors(err, RELATIONSHIP_TYPE_FIELDS, "relationship type");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section aria-labelledby="relationship-type-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="relationship-type-heading" className="mb-3 text-base font-semibold text-slate-900">
        Type
      </h2>
      <form aria-label="Relationship type" onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={RELATIONSHIP_TYPE_FIELDS} summaryRef={summaryRef} />
        {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
        <RelationshipTypeFields
          draft={draft}
          onChange={(next) => {
            setDraft(next);
            if (errors.name && next.name !== draft.name) {
              const { name: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
          entityTypes={entityTypes.data?.items ?? []}
          errors={errors}
          fallbackKey={String(type.id)}
        />
        <button
          type="submit"
          disabled={updateType.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {updateType.isPending ? "Saving…" : "Save relationship type"}
        </button>
      </form>
    </section>
  );
}

function DeleteType({ type }: { type: RelationshipType }) {
  // `relationship` rows reference `relationship_type` ON DELETE CASCADE, so
  // this count is what would be destroyed with it. One page of size 1 is
  // enough: only `total` is read. Undefined while it loads, and the
  // confirmation says so rather than claiming a number it does not have.
  const relationships = useRelationships({ relationshipTypeId: type.id, limit: 1 });
  const total = relationships.data?.total;
  const deleteType = useDeleteRelationshipType();
  const toast = useToast();
  const navigate = useNavigate();

  const cascade =
    total === undefined
      ? "every relationship of this type"
      : total === 1
        ? "its 1 relationship"
        : `its ${total} relationships`;

  async function handleDelete() {
    const confirmed = window.confirm(
      `Delete relationship type "${type.name}"? This also deletes ${cascade} — the edges themselves, not the ` +
        `entities at either end. This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await deleteType.mutateAsync(type.id);
      toast.success(`Relationship type "${type.name}" deleted`);
      navigate("/relationship-types");
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  return (
    <section aria-labelledby="delete-relationship-type-heading" className="rounded-md border border-red-200 bg-white p-4">
      <h2 id="delete-relationship-type-heading" className="mb-2 text-base font-semibold text-slate-900">
        Delete this type
      </h2>
      <p className="mb-3 text-sm text-slate-600">
        Deleting this type also deletes {cascade}. The entities at either end are not touched.
      </p>
      <button
        type="button"
        onClick={handleDelete}
        disabled={deleteType.isPending}
        className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
      >
        Delete relationship type
      </button>
    </section>
  );
}
