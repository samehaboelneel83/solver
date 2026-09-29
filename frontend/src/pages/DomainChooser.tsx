import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useEntityList } from "../api/entities";
import LoadFailure from "../components/LoadFailure";
import SearchBox, { NoMatches } from "../components/SearchBox";
import { DOMAIN_PAGES } from "../components/LegacyRedirect";

export const DOMAIN_PAGE_SIZE = 24;

/**
 * Choose a domain (Epic UX, U-1): the landing page of `/domains`, searched on the
 * server so an install with hundreds of domains still finds one by name or id.
 * `?next=data/parameters` (from an old hub link) opens that page of the chosen
 * domain instead of its overview.
 */
export default function DomainChooser() {
  const [searchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const requested = searchParams.get("next");
  // Only a page this app has: a `next` from an old link, never an arbitrary path.
  const next = requested && Object.values(DOMAIN_PAGES).includes(requested) ? requested : "overview";
  const domains = useEntityList("public", "domain", { limit: DOMAIN_PAGE_SIZE, offset, q, orderBy: "name", order: "asc" });
  const items = domains.data?.items ?? [];
  const total = domains.data?.total ?? 0;
  return (
    <section className="mx-auto max-w-4xl p-4">
      <h1 className="mb-1 text-xl font-semibold">Choose a domain</h1>
      <p className="mb-4 text-sm text-slate-600">
        A domain is the shared data for a business area; its problems are planned on it.
        {next !== "overview" && " You will go on to the page you asked for."}
      </p>
      <div className="mb-4">
        <SearchBox label="domains" onSearch={(text) => { setQ(text); setOffset(0); }} />
      </div>
      {domains.isError ? (
        <LoadFailure subject="The domain list" error={domains.error} retry={() => void domains.refetch()} />
      ) : domains.isLoading ? (
        <p role="status">Loading domains…</p>
      ) : items.length === 0 ? (
        q ? <NoMatches label="domains" q={q} /> : <p className="text-sm text-slate-600">There are no domains yet.</p>
      ) : (
        <>
          <ul className="grid gap-2 sm:grid-cols-2">
            {items.map((row) => (
              <li key={String(row.id)}>
                <Link to={`/domains/${String(row.id)}/${next}`} className="block rounded border border-slate-200 p-3 hover:bg-slate-50">
                  <span className="font-medium">{String(row.name)}</span>
                  <span className="ml-2 text-xs text-slate-500">#{String(row.id)}</span>
                  {row.description ? <span className="block text-sm text-slate-600">{String(row.description)}</span> : null}
                </Link>
              </li>
            ))}
          </ul>
          {total > DOMAIN_PAGE_SIZE && (
            <nav aria-label="Domain pages" className="mt-4 flex items-center gap-3 text-sm">
              <button type="button" className="rounded border px-2 py-1" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - DOMAIN_PAGE_SIZE))}>Previous</button>
              <span>{offset + 1}–{Math.min(offset + DOMAIN_PAGE_SIZE, total)} of {total}</span>
              <button type="button" className="rounded border px-2 py-1" disabled={offset + DOMAIN_PAGE_SIZE >= total}
                onClick={() => setOffset(offset + DOMAIN_PAGE_SIZE)}>Next</button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
