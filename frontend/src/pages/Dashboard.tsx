import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useEntityList } from "../api/entities";
import { useCounts } from "../api/counts";
import { useHealth } from "../api/health";
import { formatApiError } from "../api/errors";
import { useApplyTemplate, useTemplates } from "../api/v1";
import OfflineNotice from "../components/OfflineNotice";
import HomeResults from "../components/HomeResults";
import HomeSection, { HOME_CARD, HOME_ICON } from "../components/HomeSection";
import { Activity, Database, FlaskConical, LayoutTemplate, Play } from "lucide-react";
import { relativeTime } from "../lib/relativeTime";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { useCapabilities } from "../hooks/useCapability";

/**
 * Home (OAAS N07): continue planning from recent work, not infrastructure counts.
 */
const ENTRY_POINTS = [
  {
    href: "/public/domain",
    title: "Domains",
    description: "Shared operational data for a business area.",
    icon: Database,
  },
  {
    href: "/public/problem",
    title: "Problems",
    description: "Decisions to optimize in the selected domain.",
    icon: FlaskConical,
  },
  {
    href: "/runs",
    title: "Runs & results",
    description: "Open the latest answers and guided run views.",
    icon: Play,
  },
] as const;

/** v1's `problem` has `name`, `owner` and `created_at` -- no `code` and no
 * `status`, both of which were v0 columns this panel used to render. */
function problemDisplayName(problem: Record<string, unknown>): string {
  if (typeof problem.name === "string" && problem.name) return problem.name;
  return String(problem.id ?? "Untitled problem");
}

export default function Dashboard() {
  useDocumentTitle("Home");
  const { data: health, isLoading: healthLoading } = useHealth();
  const {
    data: counts,
    isLoading: countsLoading,
    isError: countsError,
    fetchStatus: countsFetchStatus,
  } = useCounts();
  const { domainId, setDomainId } = useDomain();
  const { can } = useCapabilities();
  const navigate = useNavigate();
  const templates = useTemplates();
  const apply = useApplyTemplate();
  const [templateError, setTemplateError] = useState<string | null>(null);
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

  const templateItems = templates.data?.items ?? [];

  return (
    <div className="max-w-7xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Home</h1>
      <p className="mb-6 text-sm text-slate-500">
        Continue planning from recent work, or start from a template.
      </p>

      <div className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {ENTRY_POINTS.map((entry) => (
          <Link key={entry.href} to={entry.href} aria-label={entry.title} className={HOME_CARD}>
            <span className={HOME_ICON} aria-hidden="true"><entry.icon size={16} /></span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-slate-900">{entry.title}</span>
              <span className="mt-0.5 block text-xs text-slate-500">{entry.description}</span>
            </span>
          </Link>
        ))}
      </div>

      <HomeSection
        id="continue-working"
        title="Continue working"
        note={`Recently created problems${domainId !== null ? " in the selected domain" : " across your domains"}.`}
        viewAll={{ to: domainId !== null ? `/domains/${domainId}/problems` : "/public/problem" }}
      >
        {problemsOffline ? (
          <OfflineNotice subject="Recent problems" />
        ) : problemsLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : problemsError ? (
          <p className="text-sm text-red-600">Failed to load recent problems</p>
        ) : recentProblems && recentProblems.items.length > 0 ? (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {recentProblems.items.map((problem) => {
              const id = String(problem.id);
              const created = relativeTime(typeof problem.created_at === "string" ? problem.created_at : null);
              const owner = typeof problem.owner === "string" && problem.owner !== "" ? problem.owner : null;
              return (
                <li key={id}>
                  <Link
                    to={problem.domain_id != null ? `/domains/${problem.domain_id}/problems/${id}/overview` : `/public/problem/${id}`}
                    className={HOME_CARD}
                  >
                    <span className={HOME_ICON} aria-hidden="true"><FlaskConical size={16} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-900">{problemDisplayName(problem)}</span>
                      <span className="mt-0.5 block truncate text-xs text-slate-500">
                        {[owner, created ? `created ${created}` : null].filter(Boolean).join(" · ") || "Problem"}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          // A-5: an empty workspace reads as "nothing here yet, here's how to
          // start" rather than looking indistinguishable from a broken fetch.
          <div className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
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
      </HomeSection>

      <HomeResults />

      {can("model.publish") && templateItems.length > 0 && (
        <HomeSection
          id="templates"
          title="Start from a template"
          note="A starting model, not a solver. Missing people, days and shifts are created if this domain does not have them yet."
        >
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {templateItems.map((row) => {
              const existing = recentProblems?.items.find(
                (problem) => Number(problem.template_id) === Number(row.id)
              );
              const label = existing ? `Open ${row.name}` : `Start from ${row.name}`;
              return (
                <li key={String(row.id)}>
                  <button
                    type="button"
                    aria-label={label}
                    disabled={apply.isPending}
                    className={`${HOME_CARD} w-full`}
                    onClick={() => {
                      if (existing) {
                        if (existing.domain_id != null) setDomainId(Number(existing.domain_id));
                        navigate(`/model?problem=${existing.id}`);
                        return;
                      }
                      setTemplateError(null);
                      apply.mutate(
                        {
                          id: row.id,
                          body:
                            domainId !== null
                              ? { domain_id: domainId }
                              : { domain_name: row.name },
                        },
                        {
                          onSuccess: (created) => {
                            setDomainId(Number(created.domain_id));
                            navigate(`/model?problem=${created.problem_id}`);
                          },
                          onError: (error: unknown) => setTemplateError(formatApiError(error)),
                        }
                      );
                    }}
                  >
                    <span className={HOME_ICON} aria-hidden="true"><LayoutTemplate size={16} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-900">{row.name}</span>
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {existing ? "Open your problem made from it" : apply.isPending ? "Starting…" : "Create a starting model"}
                      </span>
                    </span>
                    {existing && <span className="shrink-0 rounded border border-slate-200 px-1.5 py-0.5 text-xs text-slate-600">In use</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {templateError && (
            <p role="alert" className="mt-2 text-sm text-red-600">
              {templateError}
            </p>
          )}
        </HomeSection>
      )}

      <HomeSection id="system" title="System" note="Service health and what the database holds.">
        {/* A-2: one line instead of two large infrastructure cards -- this
            dashboard reports on the work, not the database. */}
        <p data-testid="service-health" className="mb-3 flex items-center gap-2 text-sm text-slate-600">
          <Activity size={14} aria-hidden="true" className="text-slate-400" />
          <span>
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
          </span>
        </p>
        {countsOffline ? (
          <OfflineNotice subject="Row counts" />
        ) : countsLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : countsError ? (
          <p className="text-sm text-red-600">Failed to load row counts</p>
        ) : counts && counts.length > 0 ? (
          <ul aria-label="Row counts" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3 lg:grid-cols-5">
            {counts.map((c) => (
              <li key={`${c.schema}.${c.table}`}>
                <Link
                  to={`/${c.schema}/${c.table}`}
                  className="flex items-center justify-between gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 hover:border-slate-300 hover:bg-slate-50"
                >
                  <span className="truncate text-slate-600">{c.label_plural}</span>
                  <span className="font-medium tabular-nums text-slate-900">{c.total}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No tables found.</p>
        )}
      </HomeSection>
    </div>
  );
}
