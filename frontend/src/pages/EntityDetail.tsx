import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import EntityForm from "../components/EntityForm";
import { formatApiError } from "../api/errors";
import { useCreateEntity, useEntity, useUpdateEntity } from "../api/entities";
import { useSchema } from "../api/meta";

export default function EntityDetail() {
  const { schemaName = "", tableName = "", id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  const { data: existing } = useEntity(schemaName, tableName, isNew ? undefined : id);
  const createEntity = useCreateEntity(schemaName, tableName);
  const updateEntity = useUpdateEntity(schemaName, tableName, id ?? "");

  if (tables && !table) {
    return (
      <p className="text-sm text-slate-400">
        Unknown table {schemaName}.{tableName}
      </p>
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
        initialValues={isNew ? undefined : existing}
        onSubmit={handleSubmit}
        submitLabel={isNew ? "Create" : "Save"}
      />
    </div>
  );
}
