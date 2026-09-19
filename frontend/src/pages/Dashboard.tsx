import { Link } from "react-router-dom";
import { useEntityList } from "../api/entities";
import { useCounts } from "../api/counts";
import { useHealth } from "../api/health";
import OfflineNotice from "../components/OfflineNotice";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";

/**
 * The three places a new user actually starts (A-1): the audit's landing
 * page named none of them -- a fresh database was just a table of 31 zeroed
 * row counts under two infrastructure cards, with nothing to click and
 * nothing explaining what the product does.
 */
const ENTRY_POINTS = [
  {
    // Schema v1: the v0 `domain.entity` table is gone. Entity types are
    // where a domain model starts -- an entity cannot exist without one.
    href: "/entity-types",
    title: "Domain model",
    description: "Entity types, their attributes, and the entities themselves.",
  },
  {
    // `problem` is a public-schema table in v1, so its generic route is
    // `/public/problem`, not the v0 `/problem/problem` (Ruling 27).
    href: "/public/problem",
    title: "Problems",
    description: "The problems this workspace is set up to solve.",
  },
  {
    href: "/graph",
    title: "Graph",
    description: "Explore the domain as a connected graph.",
  },
] as const;

/** v1's `problem` has `name`, `owner` and `created_at` -- no `code` and no
 * `status`, both of which were v0 columns this panel used to render. */
function problemDisplayName(problem: Record<string, unknown>): string {
  if (typeof problem.name === "string" && problem.name) return problem.name;
  return String(problem.id ?? "Untitled problem");
}

export default function Dashboard() {
  useDocumentTitle("Dashboard");
  const { data: health, isLoading: healthLoading } = useHealth();
  const {
    data: counts,
    isLoading: countsLoading,
    isError: countsError,
    fetchStatus: countsFetchStatus,
  } = useCounts();
  const { domainId } = useDomain();
  const {
    data: recentProblems,
    isLoading: problemsLoading,
    isError: problemsError,
    fetchStatus: problemsFetchStatus,
  } = useEntityList("public", "problem", {
    limit: 5,
    offset: 0,
    orderBy: "created_at",
    order: "desc",
    // Scoped to the domain in the sidebar when there is one; every domain's
    // problems when there is not, so a fresh session still shows something.
    filters: domainId === null ? {} : { domain_id: String(domainId) },
  });
  // D-7: offline, these queries pause instead of failing -- `isLoading` never resolves, so
  // without this each section below would show "Loading…" forever with no explanation.
  const countsOffline = countsFetchStatus === "paused" && !counts;
  const problemsOffline = problemsFetchStatus === "paused" && !recentProblems;

  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Dashboard</h1>
      <p className="mb-6 text-sm text-slate-500">Start with the domain model, or jump into a problem.</p>

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {ENTRY_POINTS.map((entry) => (
          <Link
            key={entry.href}
            to={entry.href}
            aria-label={entry.title}
            className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-300 hover:shadow-sm"
          >
            <div className="mb-1 text-sm font-semibold text-slate-900">{entry.title}</div>
            <p className="text-xs text-slate-500">{entry.description}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Recent problems</h2>
          {problemsOffline ? (
            <OfflineNotice subject="Recent problems" />
          ) : problemsLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : problemsError ? (
            <p className="text-sm text-red-600">Failed to load recent problems</p>
          ) : recentProblems && recentProblems.items.length > 0 ? (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
              {recentProblems.items.map((problem) => {
                const id = String(problem.id);
                return (
                  <li key={id}>
                    <Link
                      to={`/public/problem/${id}`}
                      className="flex items-center justify-between gap-2 px-4 py-2 text-sm hover:bg-slate-50"
                    >
                      <span className="font-medium text-blue-700">{problemDisplayName(problem)}</span>
                      {typeof problem.owner === "string" && problem.owner !== "" && (
                        <span className="text-xs text-slate-500">{problem.owner}</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            // A-5: an empty workspace reads as "nothing here yet, here's how to
            // start" rather than looking indistinguishable from a broken fetch.
            <div className="rounded-md border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
              <p>No problems yet</p>
              {/* H-9: was 20px tall with no padding -- py-1 clears the 24px Target Size floor. */}
              <Link
                to="/public/problem/new"
                className="mt-2 inline-block rounded py-1 text-sm font-medium text-blue-700 hover:underline"
              >
                New problem
              </Link>
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Service health</h2>
          {/* A-2: one line instead of two large infrastructure cards -- this
              dashboard reports on the work, not the database. */}
          <p data-testid="service-health" className="mb-6 text-sm text-slate-600">
            Postgres{" "}
            <span className={health?.postgres === "ok" ? "font-medium text-emerald-700" : "font-medium text-red-600"}>
              {healthLoading ? "…" : (health?.postgres ?? "unknown")}
            </span>
            {" · "}
            ClickHouse{" "}
            <span
              className={health?.clickhouse === "ok" ? "font-medium text-emerald-700" : "font-medium text-red-600"}
            >
              {healthLoading ? "…" : (health?.clickhouse ?? "unknown")}
            </span>
          </p>

          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Row counts</h2>
          {countsOffline ? (
            <OfflineNotice subject="Row counts" />
          ) : countsLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : countsError ? (
            <p className="text-sm text-red-600">Failed to load row counts</p>
          ) : counts && counts.length > 0 ? (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
              {counts.map((c) => (
                <li key={`${c.schema}.${c.table}`}>
                  <Link
                    to={`/${c.schema}/${c.table}`}
                    className="flex items-center justify-between px-3 py-1.5 hover:bg-slate-50"
                  >
                    <span className="text-slate-600">{c.label_plural}</span>
                    <span className="font-medium text-slate-900">{c.total}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No tables found.</p>
          )}
        </section>
      </div>
    </div>
  );
}
