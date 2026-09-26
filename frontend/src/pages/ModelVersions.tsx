import { useId } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import VersionChecks from "../components/VersionChecks";
import ShadowCard from "../components/ShadowCard";
import Skeleton from "../components/Skeleton";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import { useVersion, useVersions, type Id } from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { formatCellValue } from "../lib/format";
import { parseRouteId } from "../lib/routeId";

/**
 * A problem's model versions, read-only (Ruling 3).
 *
 * Read-only is the API's shape, not a shortcut: `model_version` is
 * immutable -- PUT, PATCH and DELETE all answer 405, the version number
 * and `ir_hash` are assigned by the database, and a new version is posted
 * from the Model editor (`/model`), not from this list. So this lists
 * what is there and shows one version's IR; it does not pretend to be
 * an editor.
 *
 * Problems come from the generic `/api/problem/` table (v1 moved `problem`
 * into `public`, Ruling 27), scoped with `?f_domain_id=`; versions come
 * from the purpose-built `/api/v1/problems/{id}/versions`, whose list
 * deliberately omits `ir` -- an IR is fetched only when one is opened.
 */

const PAGE_SIZE = 50;

export default function ModelVersions() {
  useDocumentTitle("Model versions");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Model versions</h1>
      <p className="mb-4 text-sm text-slate-500">
        Every version of a problem&rsquo;s model, newest first. Versions are immutable: a new one is created from
        the{" "}
        <Link to="/model" className="text-blue-600 underline">
          Model editor
        </Link>
        , and nothing here changes one.
      </p>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            problems.
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

function problemName(problem: Record<string, unknown>): string {
  return typeof problem.name === "string" && problem.name ? problem.name : String(problem.id ?? "");
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const chooserId = useId();
  const problems = useEntityList("public", "problem", {
    limit: 500,
    offset: 0,
    orderBy: "name",
    order: "asc",
    filters: { domain_id: String(domainId) },
  });

  if (problems.fetchStatus === "paused" && !problems.data) return <OfflineNotice subject="The problem list" />;
  if (problems.isLoading) return <Skeleton rows={3} cols={4} />;
  if (problems.isError && !problems.data) {
    return <Failed error={problems.error} onRetry={() => problems.refetch()} />;
  }

  const items = problems.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <p>This domain has no problems yet, and every model version belongs to one.</p>
        <p className="mt-1">
          Create one on the{" "}
          <Link to="/public/problem" className="inline-block rounded py-1 text-blue-600 underline">
            Problems page
          </Link>
          .
        </p>
      </div>
    );
  }

  const requested = parseRouteId(searchParams.get("problem"));
  const problem = items.find((row) => Number(row.id) === requested) ?? items[0];
  const problemId = Number(problem.id);
  const versionId = parseRouteId(searchParams.get("version"));

  return (
    <>
      <div className="mb-4">
        <label htmlFor={chooserId} className="block text-sm font-medium text-slate-700">
          Problem
        </label>
        <select
          id={chooserId}
          className="mt-1 block w-full max-w-sm rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
          value={String(problemId)}
          onChange={(event) => setSearchParams({ problem: event.target.value }, { replace: true })}
        >
          {items.map((row) => (
            <option key={String(row.id)} value={String(row.id)}>
              {problemName(row)}
            </option>
          ))}
        </select>
      </div>

      <VersionList
        key={problemId}
        problemId={problemId}
        problemLabel={problemName(problem)}
        selectedId={versionId}
        onSelect={(id) =>
          setSearchParams({ problem: String(problemId), version: String(id) }, { replace: true })
        }
      />
      <ShadowCard problemId={problemId} />
      <IrViewer versionId={versionId} />
    </>
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

function VersionList({
  problemId,
  problemLabel,
  selectedId,
  onSelect,
}: {
  problemId: Id;
  problemLabel: string;
  selectedId: Id | null;
  onSelect: (id: Id) => void;
}) {
  const { data, error, isError, isLoading, refetch, fetchStatus } = useVersions(problemId, { limit: PAGE_SIZE });

  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="The version list" />;
  if (isLoading) return <Skeleton rows={3} cols={4} />;
  if (isError && !data) return <Failed error={error} onRetry={() => refetch()} />;

  const versions = data?.items ?? [];
  if (versions.length === 0) {
    return (
      <p className="mb-6 text-sm text-slate-600">
        No versions of this problem yet. Submit a model from the{" "}
        <Link to="/model" className="text-blue-600 underline">
          Model editor
        </Link>
        ; its number and content hash are assigned when it is stored. There is no way to write one by hand.
      </p>
    );
  }

  return (
    <div className="mb-6 overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm" aria-label={`Versions of ${problemLabel}`}>
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">
              Version
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Created
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              IR hash
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Note
            </th>
          </tr>
        </thead>
        <tbody>
          {/* The API sorts newest first (`version` descending, which is not
              id order); this renders that order rather than imposing one. */}
          {versions.map((version) => {
            const created = formatCellValue({ type: "datetime" }, version.created_at);
            return (
              <tr
                key={version.id}
                className={`border-b border-slate-100 last:border-0 ${
                  version.id === selectedId ? "bg-slate-50" : ""
                }`}
              >
                <th scope="row" className="px-3 py-2 font-normal">
                  <button
                    type="button"
                    aria-label={`Version ${version.version}`}
                    aria-current={version.id === selectedId ? "true" : undefined}
                    onClick={() => onSelect(version.id)}
                    className="rounded py-1 font-mono text-blue-600 underline hover:text-blue-800"
                  >
                    {version.version}
                  </button>
                </th>
                <td className="whitespace-nowrap px-3 py-2 text-slate-700">
                  <time dateTime={version.created_at} title={version.created_at}>
                    {created.text}
                  </time>
                </td>
                <td className="px-3 py-2 font-mono text-slate-700">{version.ir_hash}</td>
                <td className="px-3 py-2 text-slate-700">{version.note ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function IrViewer({ versionId }: { versionId: Id | null }) {
  const { data, error, isError, isLoading, fetchStatus } = useVersion(versionId);

  if (versionId === null) {
    return <p className="text-sm text-slate-600">Choose a version above to see the model it holds.</p>;
  }
  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="This version" />;
  if (isLoading) return <Skeleton rows={6} cols={1} />;
  if (isError && !data) return <p className="text-sm text-red-600">{formatApiError(error)}</p>;
  if (!data) return null;

  return (
    <section aria-labelledby="ir-heading">
      <h2 id="ir-heading" className="mb-2 text-base font-semibold text-slate-900">
        Version {data.version} &mdash; model IR
      </h2>
      <VersionChecks versionId={versionId} />
      <pre
        data-testid="version-ir"
        tabIndex={0}
        aria-label={`Model IR of version ${data.version}`}
        className="max-h-[60vh] overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800"
      >
        {JSON.stringify(data.ir, null, 2)}
      </pre>
    </section>
  );
}
