import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DataTable from "../components/DataTable";
import { useDeleteEntity, useEntityList } from "../api/entities";
import { useSchema } from "../api/meta";

const PAGE_SIZE = 20;

export default function EntityList() {
  const { schemaName = "", tableName = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  const { data, isLoading, error } = useEntityList(schemaName, tableName, PAGE_SIZE, offset);
  const deleteEntity = useDeleteEntity(schemaName, tableName);

  if (!table) {
    return <p className="text-sm text-slate-400">Loading table definition…</p>;
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">
          {schemaName}.{tableName}
        </h1>
        <Link
          to={`/${schemaName}/${tableName}/new`}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
        >
          New
        </Link>
      </div>
      {isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">Failed to load rows</p>}
      {data && (
        <DataTable
          fields={table.fields}
          rows={data.items}
          total={data.total}
          limit={PAGE_SIZE}
          offset={offset}
          onPageChange={setOffset}
          onDelete={(id) => deleteEntity.mutate(id)}
          onRowClick={(id) => navigate(`/${schemaName}/${tableName}/${id}`)}
        />
      )}
    </div>
  );
}
