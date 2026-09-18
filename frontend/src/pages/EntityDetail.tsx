import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import EntityForm, { type ServerFieldError } from "../components/EntityForm";
import RelatedRecords from "../components/RelatedRecords";
import { useToast } from "../components/ToastProvider";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCreateEntity, useEntity, useUpdateEntity } from "../api/entities";
import { useSchema } from "../api/meta";
import { useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
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
  const isNew = id === undefined;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [serverFieldError, setServerFieldError] = useState<ServerFieldError | null>(null);
  const toast = useToast();
  const confirmLeave = useConfirmLeave();

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);
  const listUrl = `/${schemaName}/${tableName}`;

  const {
    data: existing,
    error: entityError,
    isError: isEntityError,
    refetch: refetchEntity,
  } = useEntity(schemaName, tableName, isNew ? undefined : id);
  const createEntity = useCreateEntity(schemaName, tableName);
  const updateEntity = useUpdateEntity(schemaName, tableName, id ?? "");

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
          <p className="text-sm text-slate-500">{table ? tableLabel(table) : "Record"} not found</p>
          <Link to={`/${schemaName}/${tableName}`} className="text-sm text-blue-600 underline">
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
        <Link to={`/${schemaName}/${tableName}`} className="text-sm text-blue-600 underline">
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
        <Link to={listUrl} onClick={handleNavClick} className="text-blue-600 underline">
          {table ? tableLabelPlural(table) : `${schemaName}.${tableName}`}
        </Link>
      </nav>
      <h1 className="text-lg font-semibold text-slate-900">{pageTitle}</h1>
      <p className="mb-4 text-xs text-slate-500">
        {schemaName}.{tableName}
      </p>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <EntityForm
        fields={table.fields}
        initialValues={isNew ? prefill : existing}
        onSubmit={handleSubmit}
        submitLabel={isNew ? "Create" : "Save"}
        isEdit={!isNew}
        isSubmitting={createEntity.isPending || updateEntity.isPending}
        serverError={serverFieldError}
      />
      <div className="mt-2 max-w-xl">
        <Link
          to={listUrl}
          onClick={handleNavClick}
          className="text-sm text-slate-600 underline hover:text-slate-900"
        >
          Cancel
        </Link>
      </div>
      {!isNew && id && <RelatedRecords schema={schemaName} table={tableName} id={id} />}
    </div>
  );
}
