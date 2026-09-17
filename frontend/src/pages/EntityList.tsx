import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import DataTable from "../components/DataTable";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import { useDeleteEntity, useEntityList } from "../api/entities";
import { useSchema } from "../api/meta";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { tableLabelPlural } from "../lib/labels";

const PAGE_SIZE = 20;
const FILTER_PREFIX = "f_";
const SEARCH_DEBOUNCE_MS = 300;

export default function EntityList() {
  const { schemaName = "", tableName = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const toast = useToast();

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  // Shared fallback while the schema is still loading (or for a route with
  // no params at all): the raw "schema.table" pair, so there's always a
  // heading/title rather than a blank one during the load.
  const rawTableName = schemaName && tableName ? `${schemaName}.${tableName}` : "List";
  const headingLabel = table ? tableLabelPlural(table) : rawTableName;

  useDocumentTitle(headingLabel);

  const q = searchParams.get("q") ?? "";
  const offset = Number(searchParams.get("offset") ?? "0") || 0;
  const orderBy = searchParams.get("order_by") ?? undefined;
  const orderParam = searchParams.get("order");
  const order = orderParam === "asc" || orderParam === "desc" ? orderParam : undefined;

  const filters = useMemo(() => {
    const result: Record<string, string> = {};
    for (const [key, value] of searchParams.entries()) {
      if (key.startsWith(FILTER_PREFIX)) {
        result[key.slice(FILTER_PREFIX.length)] = value;
      }
    }
    return result;
  }, [searchParams]);

  const [searchInput, setSearchInput] = useState(q);

  // Keep the input in sync when the URL changes from elsewhere (back/forward).
  useEffect(() => {
    setSearchInput(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  // Debounce the search box before it hits the URL/request.
  useEffect(() => {
    if (searchInput === q) return;
    const timer = setTimeout(() => {
      const next = new URLSearchParams(searchParams);
      if (searchInput) {
        next.set("q", searchInput);
      } else {
        next.delete("q");
      }
      next.delete("offset");
      setSearchParams(next, { replace: true });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  const { data, isLoading, error, refetch } = useEntityList(schemaName, tableName, {
    limit: PAGE_SIZE,
    offset,
    q,
    filters,
    orderBy,
    order,
  });
  const deleteEntity = useDeleteEntity(schemaName, tableName);

  // "meta loaded, no match" is a terminal state distinct from loading --
  // keep it as an early return so it's never confused with the skeleton
  // below (which covers "meta hasn't resolved yet at all").
  if (tables && !table) {
    return (
      <p className="text-sm text-slate-500">
        Unknown table {schemaName}.{tableName}
      </p>
    );
  }

  function updateParams(mutator: (params: URLSearchParams) => void) {
    const next = new URLSearchParams(searchParams);
    mutator(next);
    setSearchParams(next);
  }

  function handlePageChange(newOffset: number) {
    updateParams((params) => {
      if (newOffset > 0) {
        params.set("offset", String(newOffset));
      } else {
        params.delete("offset");
      }
    });
  }

  function handleSort(column: string) {
    updateParams((params) => {
      if (orderBy === column && order === "asc") {
        params.set("order_by", column);
        params.set("order", "desc");
      } else if (orderBy === column && order === "desc") {
        params.delete("order_by");
        params.delete("order");
      } else {
        params.set("order_by", column);
        params.set("order", "asc");
      }
      params.delete("offset");
    });
  }

  function removeFilter(key: string) {
    updateParams((params) => {
      params.delete(`${FILTER_PREFIX}${key}`);
      params.delete("offset");
    });
  }

  const newLinkParams = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    newLinkParams.set(key, value);
  }
  const newLinkQuery = newLinkParams.toString();

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{headingLabel}</h1>
          <p className="text-xs text-slate-500">
            {schemaName}.{tableName}
          </p>
        </div>
        <Link
          to={`/${schemaName}/${tableName}/new${newLinkQuery ? `?${newLinkQuery}` : ""}`}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
        >
          New
        </Link>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          data-testid="list-search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search…"
          className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
        {Object.entries(filters).map(([key, value]) => (
          <span
            key={key}
            className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600"
          >
            <span>
              {key} = {value}
            </span>
            <button
              type="button"
              onClick={() => removeFilter(key)}
              aria-label={`Remove filter ${key}`}
              className="text-slate-500 hover:text-slate-700"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      {deleteError && <p className="mb-3 text-sm text-red-600">{deleteError}</p>}
      {/* Covers both "list still loading" AND "schema (table.fields) hasn't
          resolved yet" -- the two queries run concurrently, so on a cold
          navigation there is no window where `table` is known but the list
          is still loading (or vice versa) without this OR. Skipped once an
          error has already replaced the loading state below. */}
      {(isLoading || !table) && !error && (
        <Skeleton rows={PAGE_SIZE > 10 ? 8 : PAGE_SIZE} cols={table ? table.fields.length + 1 : 4} />
      )}
      {error && (
        <div className="mb-3 flex items-center gap-3 text-sm text-red-600">
          <p>{formatApiError(error)}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            Retry
          </button>
        </div>
      )}
      {data && table && (
        <DataTable
          key={`${schemaName}.${tableName}`}
          fields={table.fields}
          rows={data.items}
          total={data.total}
          limit={PAGE_SIZE}
          offset={offset}
          orderBy={orderBy}
          order={order}
          onSort={handleSort}
          onPageChange={handlePageChange}
          onDelete={(id, label) => {
            setDeleteError(null);
            deleteEntity.mutate(id, {
              onSuccess: () => toast.success(`${label} deleted`),
              onError: (err) => setDeleteError(formatApiError(err)),
            });
          }}
          onRowClick={(id) => navigate(`/${schemaName}/${tableName}/${id}`)}
        />
      )}
    </div>
  );
}
