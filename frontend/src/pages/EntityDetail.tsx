import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import EntityForm, { type ServerFieldError } from "../components/EntityForm";
import OfflineNotice from "../components/OfflineNotice";
import RelatedRecords from "../components/RelatedRecords";
import { useToast } from "../components/ToastProvider";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCreateEntity, useEntity, useUpdateEntity } from "../api/entities";
import { useSchema } from "../api/meta";
import { useCapabilities } from "../hooks/useCapability";
import { useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useShowIdentifiers } from "../hooks/useShowIdentifiers";
import { fieldLabel, lowerFirst, recordLabel, tableLabel, tableLabelPlural } from "../lib/labels";
import type { FieldMeta } from "../types/meta";

/**
 * C-5: a 409 (unique-constraint violation) detail from the backend names
 * the raw DB constraint, e.g. "a entity_type row with the same
 * organization_id_code already exists" -- meaningless (and a schema-detail
 * leak) to an end user, and the field it's about isn't marked. Maps it to
 * one of the table's own writable fields when the detail text contains
 * that field's column name, preferring a non-FK field (the value the user
 * actually typed) over an FK field that happens to share the constraint.
 * Returns null when no known field name is found -- callers fall back to
 * showing the backend's own wording unchanged.
 */
export function mapConstraintError(detail: string, fields: FieldMeta[]): { field: string; label: string } | null {
  const writable = fields.filter((f) => f.writable && f.name.length > 0);
  const matches = (f: FieldMeta) => detail.includes(f.name);
  const nonFkMatches = writable.filter((f) => !f.is_fk && matches(f));
  const pool = nonFkMatches.length > 0 ? nonFkMatches : writable.filter(matches);
  if (pool.length === 0) return null;
  // Prefer the most specific (longest) matching column name.
  const [best] = [...pool].sort((a, b) => b.name.length - a.name.length);
  return { field: best.name, label: fieldLabel(best) };
}

export default function EntityDetail() {
  const { schemaName = "", tableName = "", id } = useParams();
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const isNew = id === undefined;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [serverFieldError, setServerFieldError] = useState<ServerFieldError | null>(null);
  const toast = useToast();
  const confirmLeave = useConfirmLeave();

  const { data: tables, fetchStatus: schemaFetchStatus } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);
  const listUrl = `/${schemaName}/${tableName}`;
  const [showIds, toggleShowIds] = useShowIdentifiers();

  const {
    data: existing,
    error: entityError,
    isError: isEntityError,
    refetch: refetchEntity,
    fetchStatus: entityFetchStatus,
  } = useEntity(schemaName, tableName, isNew ? undefined : id);
  const createEntity = useCreateEntity(schemaName, tableName);
  const updateEntity = useUpdateEntity(schemaName, tableName, id ?? "");

  // D-7: same reasoning as EntityList -- offline, these queries pause rather than fail, so
  // without this the "Loading…" state below would never resolve or explain itself.
  const isOffline =
    (schemaFetchStatus === "paused" && !tables) ||
    (!isNew && entityFetchStatus === "paused" && !existing);

  // B-3: a domain.entity record IS a graph node (same id) -- the graph filters strictly by
  // organization_id (see backend/app/graph/service.py get_domain_graph), so a deep link needs
  // both. Only domain.entity rows back a graph node at all (entity_type, hierarchy, etc. do
  // not), so this is scoped to that one table rather than showing a dead link everywhere.
  const isDomainEntity = schemaName === "domain" && tableName === "entity";
  const entityOrganizationId =
    existing && typeof existing.organization_id === "string" ? existing.organization_id : undefined;
  const graphHref =
    isDomainEntity && !isNew && id && entityOrganizationId
      ? `/graph?focus=${encodeURIComponent(id)}&org=${encodeURIComponent(entityOrganizationId)}`
      : null;

  // C-6: "Edit entity type" used to be identical for every row. On edit,
  // name the actual record (its `label_field` columns, e.g. "acme") when
  // the schema has one; "New" has no record yet, so it keeps the generic
  // table-name form. Falls back to the raw schema.table pair while the
  // schema is still loading.
  const recordName = !isNew ? recordLabel(table ?? { fields: [] }, existing) : undefined;
  const genericTitle = table ? lowerFirst(tableLabel(table)) : `${schemaName}.${tableName}`;
  const pageTitle = isNew ? `New ${genericTitle}` : `Edit ${recordName ?? genericTitle}`;
  useDocumentTitle(pageTitle);

  function handleNavClick(event: { preventDefault: () => void }) {
    if (!confirmLeave()) {
      event.preventDefault();
    }
  }

  // Prefill new-record fields from the query string, e.g. a "New" link
  // carrying the list's current filters (?entity_type_id=abc) -- only for
  // params that actually name a writable field on this table.
  const prefill = useMemo(() => {
    if (!isNew || !table) return undefined;
    const writableNames = new Set(table.fields.filter((f) => f.writable).map((f) => f.name));
    const values: Record<string, unknown> = {};
    for (const [key, value] of searchParams.entries()) {
      if (writableNames.has(key)) {
        values[key] = value;
      }
    }
    return Object.keys(values).length > 0 ? values : undefined;
  }, [isNew, table, searchParams]);

  if (isOffline) {
    return <OfflineNotice subject="This page" />;
  }

  if (tables && !table) {
    return (
      <p className="text-sm text-slate-500">
        Unknown table {schemaName}.{tableName}
      </p>
    );
  }

  if (!isNew && isEntityError) {
    if (entityError instanceof ApiError && entityError.status === 404) {
      return (
        <div>
          {/* See EntityTypeDetail: a page with no <h1> is an axe
              `page-has-heading-one` violation. */}
          <h1 className="mb-2 text-lg font-semibold text-slate-900">
            {table ? tableLabel(table) : "Record"} not found
          </h1>
          {/* H-9: a full target-size sweep found these standalone "Back to list" links --
              plain text-sm with no padding -- at 20px tall, still under the 24px floor.
              inline-block + py-1 brings them to 28px without changing their visual style. */}
          <Link to={`/${schemaName}/${tableName}`} className="inline-block rounded py-1 text-sm text-blue-600 underline">
            Back to list
          </Link>
        </div>
      );
    }
    return (
      <div>
        <div className="mb-2 flex items-center gap-3">
          <p className="text-sm text-red-600">{formatApiError(entityError)}</p>
          <button
            type="button"
            onClick={() => refetchEntity()}
            className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            Retry
          </button>
        </div>
        <Link to={`/${schemaName}/${tableName}`} className="inline-block rounded py-1 text-sm text-blue-600 underline">
          Back to list
        </Link>
      </div>
    );
  }

  if (!table || (!isNew && !existing)) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  async function handleSubmit(values: Record<string, unknown>) {
    if (!table) return; // unreachable: the early "Loading…" return above guarantees this by the time the form can submit
    setError(null);
    setServerFieldError(null);
    const recordTypeLabel = table ? tableLabel(table) : "Record";
    try {
      if (isNew) {
        await createEntity.mutateAsync(values);
        toast.success(`${recordTypeLabel} created`);
      } else {
        await updateEntity.mutateAsync(values);
        toast.success(`${recordTypeLabel} saved`);
      }
      navigate(listUrl);
    } catch (err) {
      const message = formatApiError(err);
      // C-5: a 409 names the raw DB constraint (e.g.
      // "...organization_id_code already exists"), which leaks schema
      // internals and doesn't mark the offending field. When the detail
      // text names a known column, show a clean field-specific message
      // instead (never the raw constraint string) and mark that field;
      // otherwise fall back to the backend's own wording unchanged.
      if (err instanceof ApiError && err.status === 409) {
        const mapped = mapConstraintError(message, table.fields);
        if (mapped) {
          setServerFieldError({ field: mapped.field, message: `${mapped.label}: a record with this value already exists.` });
          return;
        }
      }
      setError(message);
    }
  }

  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-2 text-sm">
        {/* H-9: was plain text-sm with no padding (20px tall) -- inline-block + py-1 clears
            the 24px Target Size floor. */}
        <Link to={listUrl} onClick={handleNavClick} className="inline-block rounded py-1 text-blue-600 underline">
          {table ? tableLabelPlural(table) : `${schemaName}.${tableName}`}
        </Link>
      </nav>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-slate-900">{pageTitle}</h1>
        {/* B-1: same "Show identifiers" flag as the list page's DataTable, so this page's own
            schema.table subtitle is gated too -- there was no toggle here before this fix, which
            is why the raw pair used to render unconditionally. */}
        <button
          type="button"
          onClick={toggleShowIds}
          aria-pressed={showIds}
          className="rounded px-2 py-2 text-xs text-slate-500 underline hover:text-slate-700"
        >
          {showIds ? "Hide identifiers" : "Show identifiers"}
        </button>
      </div>
      {showIds && (
        <p className="mb-4 text-xs text-slate-500" data-testid="schema-subtitle">
          {schemaName}.{tableName}
        </p>
      )}
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <EntityForm
        fields={table.fields}
        initialValues={isNew ? prefill : existing}
        onSubmit={handleSubmit}
        submitLabel={isNew ? "Create" : "Save"}
        isEdit={!isNew}
        isSubmitting={createEntity.isPending || updateEntity.isPending}
        serverError={serverFieldError}
        readOnly={!canEdit}
      />
      <div className="mt-2 flex max-w-xl items-center gap-4">
        {/* H-9: same fix as the breadcrumb above -- inline-block + py-1 for a 24px+ tall target. */}
        <Link
          to={listUrl}
          onClick={handleNavClick}
          className="inline-block rounded py-1 text-sm text-slate-600 underline hover:text-slate-900"
        >
          Cancel
        </Link>
        {/* B-3: the other half of the finding -- the admin form's vocabulary already matched
            the graph panel's, but there was no way to get from a record to the graph at all.
            Reuses GraphDemo's existing focus/selection mechanism (searchFocus/focusRequest)
            via a plain deep-link query string rather than inventing a second selection path. */}
        {graphHref && (
          <Link
            to={graphHref}
            className="inline-block rounded py-1 text-sm text-blue-600 underline hover:text-blue-800"
            data-testid="open-in-graph-link"
          >
            Open in graph
          </Link>
        )}
      </div>
      {!isNew && id && <RelatedRecords schema={schemaName} table={tableName} id={id} />}
    </div>
  );
}
