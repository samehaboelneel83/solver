import { FormEvent, useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatAttrValue } from "../components/AttrsForm";
import { INPUT_CLASS } from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { formatApiError } from "../api/errors";
import { useEntities, useEntityTypes, type EntityType, type Id } from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

/**
 * The selected domain's entities, one entity type at a time.
 *
 * The type chooser is not a convenience: `GET /api/v1/entities` has no
 * `domain_id` filter (Task 10's finding), only `entity_type_id`, and a
 * domain-wide list would have to fan out one request per type and merge
 * them -- with no way to page the result. A type also decides which
 * columns the table has, since they are its `attribute_def` rows.
 *
 * The chosen type lives in the query string so a list can be linked to and
 * survives a reload, and so the "New entity" link can carry it.
 */

const PAGE_SIZE = 50;

export default function Entities() {
  useDocumentTitle("Entities");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Entities</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            entities.
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
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const types = useEntityTypes(domainId, { limit: 500 });
  const items = types.data?.items ?? [];

  const requested = parseRouteId(searchParams.get("type"));
  const selected = items.find((type) => type.id === requested) ?? items[0] ?? null;

  if (types.fetchStatus === "paused" && !types.data) return <OfflineNotice subject="The entity list" />;
  if (types.isLoading) return <Skeleton rows={3} cols={4} />;
  if (types.isError && !types.data) {
    return <Failed error={types.error} onRetry={() => types.refetch()} />;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <p>This domain has no entity types yet, and every entity belongs to one.</p>
        <p className="mt-1">
          <Link to="/entity-types" className="inline-block rounded py-1 text-blue-600 underline">
            Define an entity type first
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <>
      <TypeChooser
        types={items}
        selected={selected}
        onSelect={(id) => setSearchParams({ type: String(id) }, { replace: true })}
      />
      {selected && <EntityTable key={selected.id} type={selected} />}
    </>
  );
}

function TypeChooser({
  types,
  selected,
  onSelect,
}: {
  types: EntityType[];
  selected: EntityType | null;
  onSelect: (id: Id) => void;
}) {
  const id = useId();
  return (
    <div className="mb-4 flex flex-wrap items-end gap-4">
      <div>
        <label htmlFor={id} className="block text-sm font-medium text-slate-700">
          Entity type
        </label>
        <select
          id={id}
          className={`${INPUT_CLASS} font-mono`}
          value={selected ? String(selected.id) : ""}
          onChange={(event) => onSelect(Number(event.target.value))}
        >
          {types.map((type) => (
            <option key={type.id} value={type.id}>
              {type.name}
            </option>
          ))}
        </select>
      </div>
      {selected && (
        <Link
          to={`/entities/new?type=${selected.id}`}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        >
          New entity
        </Link>
      )}
    </div>
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <p className="text-sm text-red-600">{formatApiError(error)}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
      >
        Retry
      </button>
    </div>
  );
}

function EntityTable({ type }: { type: EntityType }) {
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const searchId = useId();
  const { data, error, isError, isLoading, refetch, fetchStatus } = useEntities(type.id, {
    q: q || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  // A narrower search can leave the current page past the end of the result.
  useEffect(() => setOffset(0), [q]);

  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="The entity list" />;
  if (isLoading) return <Skeleton rows={4} cols={4} />;
  if (isError && !data) return <Failed error={error} onRetry={() => refetch()} />;

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <>
      <form
        className="mb-4 flex flex-wrap items-end gap-2"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          setQ(draft.trim());
        }}
      >
        <div>
          <label htmlFor={searchId} className="block text-sm font-medium text-slate-700">
            Search
          </label>
          <input
            id={searchId}
            type="search"
            autoComplete="off"
            className={INPUT_CLASS}
            placeholder="key or label"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </div>
        <button
          type="submit"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        >
          Search
        </button>
      </form>

      {rows.length === 0 ? (
        <p className="text-sm text-slate-600">
          {q
            ? `No entities of this type match "${q}".`
            : "No entities of this type yet. Create the first one with “New entity” above."}
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
            <table className="w-full text-left text-sm" aria-label={`Entities of type ${type.name}`}>
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-3 py-2 font-semibold">
                    Key
                  </th>
                  <th scope="col" className="px-3 py-2 font-semibold">
                    Label
                  </th>
                  <th scope="col" className="px-3 py-2 font-semibold">
                    Sort order
                  </th>
                  <th scope="col" className="px-3 py-2 font-semibold">
                    Active
                  </th>
                  {type.attributes.map((attribute) => (
                    <th key={attribute.id} scope="col" className="px-3 py-2 font-mono font-semibold normal-case">
                      {attribute.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((entity) => (
                  <tr key={entity.id} className="border-b border-slate-100 last:border-0">
                    <th scope="row" className="px-3 py-2 font-normal">
                      <Link to={`/entities/${entity.id}`} className="inline-block rounded py-1 font-mono text-blue-600 underline">
                        {entity.key}
                      </Link>
                    </th>
                    <td className="px-3 py-2 text-slate-700">{entity.label ?? "—"}</td>
                    <td className="px-3 py-2 text-slate-700">{entity.sort_order}</td>
                    <td className="px-3 py-2 text-slate-700">{entity.active ? "Yes" : "No"}</td>
                    {type.attributes.map((attribute) => (
                      <td key={attribute.id} className="px-3 py-2 text-slate-700">
                        {formatAttrValue(entity.attrs?.[attribute.name])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {total > PAGE_SIZE && (
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-600">
              <span>
                {offset + 1}&ndash;{Math.min(offset + rows.length, total)} of {total}
              </span>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + rows.length >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
