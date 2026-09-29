import { useId, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCreateEntity, useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
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
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <SearchBox label="domains" onSearch={(text) => { setQ(text); setOffset(0); }} />
        <CreateDomain next={next} />
      </div>
      {domains.isError ? (
        <LoadFailure subject="The domain list" error={domains.error} retry={() => void domains.refetch()} />
      ) : domains.isLoading ? (
        <p role="status">Loading domains…</p>
      ) : items.length === 0 ? (
        q ? <NoMatches label="domains" q={q} /> : (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-700">
            <p className="font-medium">There are no domains yet.</p>
            <p className="mt-1">
              Create one above and add its records, or{" "}
              <Link to="/#templates" className="text-blue-700 underline">start from a template on Home</Link>: a template
              makes a domain with sample data, a model and a scenario you can solve at once.
            </p>
          </div>
        )
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

/**
 * A new domain, named here (first-run fix F1/F5): an empty install needs a way in that is
 * not a template. Offered to accounts that may edit domains; the server checks it again.
 */
function CreateDomain({ next }: { next: string }) {
  const id = useId();
  const { can } = useCapabilities();
  const { setDomainId } = useDomain();
  const navigate = useNavigate();
  const create = useCreateEntity("public", "domain");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  if (!can("domain.edit")) return null;
  if (!open) {
    return (
      <button type="button" className="rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white" onClick={() => setOpen(true)}>
        Create a domain
      </button>
    );
  }
  return (
    <form
      aria-label="Create a domain"
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate({ name: name.trim() }, {
          onSuccess: (created) => {
            const domainId = Number((created as { id: number }).id);
            setDomainId(domainId);
            navigate(`/domains/${domainId}/${next}`);
          },
        });
      }}
    >
      <label htmlFor={`${id}-name`} className="text-sm">
        <span className="block text-slate-700">Name of the business area</span>
        <input id={`${id}-name`} autoFocus value={name} onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Hospital staffing" className="mt-1 w-64 rounded-md border border-slate-300 px-2 py-1" />
      </label>
      <button type="submit" disabled={!name.trim() || create.isPending} className="rounded-md bg-blue-700 px-3 py-2 text-sm text-white disabled:opacity-50">
        {create.isPending ? "Creating…" : "Create"}
      </button>
      <button type="button" className="rounded-md border px-3 py-2 text-sm" onClick={() => setOpen(false)}>Cancel</button>
      {create.isError && <p role="alert" className="w-full text-sm text-red-700">{formatApiError(create.error)}</p>}
    </form>
  );
}
