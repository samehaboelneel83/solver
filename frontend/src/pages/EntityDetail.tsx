import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import EntityForm from "../components/EntityForm";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCreateEntity, useEntity, useUpdateEntity } from "../api/entities";
import { useSchema } from "../api/meta";

export default function EntityDetail() {
  const { schemaName = "", tableName = "", id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  const {
    data: existing,
    error: entityError,
    isError: isEntityError,
  } = useEntity(schemaName, tableName, isNew ? undefined : id);
  const createEntity = useCreateEntity(schemaName, tableName);
  const updateEntity = useUpdateEntity(schemaName, tableName, id ?? "");

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
      <p className="text-sm text-slate-400">
        Unknown table {schemaName}.{tableName}
      </p>
    );
  }

  if (!isNew && isEntityError && entityError instanceof ApiError && entityError.status === 404) {
    return (
      <div>
        <p className="text-sm text-slate-400">Record not found</p>
        <Link to={`/${schemaName}/${tableName}`} className="text-sm text-blue-600 underline">
          Back to list
        </Link>
      </div>
    );
  }

  if (!table || (!isNew && !existing)) {
    return <p className="text-sm text-slate-400">Loading…</p>;
  }

  async function handleSubmit(values: Record<string, unknown>) {
    setError(null);
    try {
      if (isNew) {
        await createEntity.mutateAsync(values);
      } else {
        await updateEntity.mutateAsync(values);
      }
      navigate(`/${schemaName}/${tableName}`);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">
        {isNew ? "New" : "Edit"} {schemaName}.{tableName}
      </h1>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <EntityForm
        fields={table.fields}
        initialValues={isNew ? prefill : existing}
        onSubmit={handleSubmit}
        submitLabel={isNew ? "Create" : "Save"}
      />
    </div>
  );
}
