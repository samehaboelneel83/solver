import LoadFailure from "../components/LoadFailure";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, FileStack, GitBranch, Play, Workflow } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useEntityList } from "../api/entities";
import { useDomains, useDomainDetail, useScenarios, useVersions } from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

const card = "rounded-2xl border border-slate-200 bg-white p-5";
const link = "inline-flex items-center gap-2 rounded-md py-2 text-sm font-semibold text-blue-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";

export function DomainOverview({ listing = false }: { listing?: boolean }) {
  const { domainId: raw } = useParams();
  const domainId = parseRouteId(raw ?? null);
  return domainId === null ? <p role="alert">Choose a valid domain.</p>
    : <DomainContent key={domainId} domainId={domainId} listing={listing} />;
}

function DomainContent({ domainId, listing }: { domainId: number; listing: boolean }) {
  const domains = useDomains();
  const listed = domains.data?.items.find((item) => item.id === domainId);
  const detail = useDomainDetail(domains.data && !listed ? domainId : null);
  const name = listed?.name ?? (detail.data?.id === domainId ? detail.data.name : "Domain");
  const { can } = useCapabilities();
  const [search, setSearch] = useSearchParams();
  const page = parseRouteId(search.get("page")) ?? 1;
  const q = search.get("q") ?? "";
  const problems = useEntityList("public", "problem", {
    limit: 12, offset: (page - 1) * 12, q,
    filters: { domain_id: String(domainId) }, orderBy: "name", order: "asc",
  });
  useDocumentTitle(`${listing ? "Problems" : "Overview"} · ${name}`);
  const base = `/domains/${domainId}`;
  const pending = problems.isLoading || problems.isPlaceholderData;
  function change(values: Record<string, string>) {
    const next = new URLSearchParams(search);
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setSearch(next);
  }
  return <div className="max-w-6xl space-y-6">
    <Link className={link} to="/domains">All domains</Link>
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold text-slate-900">{listing ? `${name} problems` : name}</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">Shared data for this business area. Choose a problem to continue planning, or prepare its inputs.</p></div>
      {can("domain.edit") && <Link className={link} to={`/public/problem/new?f_domain_id=${domainId}`}>New problem <ArrowRight size={16} aria-hidden /></Link>}
    </header>
    {!listing && <section aria-label="Domain data" className="grid gap-4 md:grid-cols-3">
      {[
        { label: "Records & relationships", detail: "People, places, resources and other operational data.", href: "data", Icon: Database },
        { label: "Parameters", detail: "Demand, capacities, costs and other model inputs.", href: "data/parameters", Icon: FileStack },
        { label: "Data relationships (graph)", detail: "Explore locations and connections in your data.", href: "data/explore", Icon: GitBranch },
      ].map(({ label, detail, href, Icon }) => <article key={href} className={card}>
        <Icon className="mb-3 h-5 w-5 text-blue-700" aria-hidden />
        <h2 className="font-semibold text-slate-900"><Link className={link} to={`${base}/${href}`}>{label}</Link></h2>
        <p className="text-sm text-slate-600">{detail}</p>
      </article>)}
    </section>}
    <section className={card} aria-labelledby="domain-problems-heading">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 id="domain-problems-heading" className="text-lg font-semibold text-slate-900">Planning problems</h2>
        <label className="text-sm text-slate-600">Find a problem
          <input type="search" className="ms-3 rounded-lg border border-slate-300 px-3 py-2"
            value={q} onChange={(event) => change({ q: event.target.value, page: "" })} />
        </label>
      </div>
      {pending ? <p role="status" className="py-6 text-sm text-slate-600">Loading problems…</p>
        : problems.isError ? <LoadFailure subject="The problem list" error={problems.error} retry={() => void problems.refetch()} />
        : <>
          <p className="mt-2 text-sm text-slate-500" aria-live="polite">{problems.data?.total ?? 0} problems{q ? " matching your search" : " in this domain"}</p>
          {problems.data?.items.length ? <ul className="mt-4 divide-y divide-slate-100">
            {problems.data.items.map((problem) => <li key={String(problem.id)}>
              <Link to={`${base}/problems/${problem.id}/overview`} className="flex items-center justify-between gap-3 rounded-lg px-2 py-4 hover:bg-slate-50">
                <span><span className="block font-medium text-slate-900">{String(problem.name)}</span>
                  {typeof problem.owner === "string" && problem.owner && <span className="text-sm text-slate-500">Owner: {problem.owner}</span>}
                </span><ArrowRight size={18} className="text-slate-500" aria-hidden />
              </Link>
            </li>)}
          </ul> : <p className="py-6 text-sm text-slate-600">{q ? "No problems match this search." : "No problems on this page. Create a problem or choose a template to get started."}</p>}
          {(page > 1 || (problems.data?.total ?? 0) > 12) && <nav aria-label="Problem pages" className="mt-4 flex items-center gap-4">
            <button className={link} disabled={page <= 1} onClick={() => change({ page: String(page - 1) })}>Previous</button>
            <span className="text-sm text-slate-600">Page {page}</span>
            <button className={link} disabled={page * 12 >= (problems.data?.total ?? 0)} onClick={() => change({ page: String(page + 1) })}>Next</button>
          </nav>}
        </>}
    </section>
    <p className="text-sm text-slate-500">Domain data is shared by its problems. Use a scenario when exploring different assumptions.</p>
  </div>;
}

export function ProblemOverview() {
  const params = useParams();
  const domainId = parseRouteId(params.domainId ?? null);
  const problemId = parseRouteId(params.problemId ?? null);
  const problem = useQuery({
    queryKey: ["entities", "public", "problem", problemId],
    queryFn: () => apiFetch<{ id: number; domain_id: number; name: string; owner?: string }>(`/api/problem/${problemId}`),
    enabled: problemId !== null,
  });
  const versions = useVersions(problemId, { limit: 1, offset: 0 });
  const scenarios = useScenarios(problemId, { limit: 5, offset: 0 });
  const { can } = useCapabilities();
  useDocumentTitle(`${problem.data?.name ?? "Problem"} · Overview`);
  const base = `/domains/${domainId}/problems/${problemId}`;
  const checks = [problem, versions, scenarios];
  const failed = checks.find((query) => query.isError);
  if (failed) return <LoadFailure subject="The problem overview" error={failed.error} retry={() => void failed.refetch()} />;
  if (checks.some((query) => query.isLoading)) return <p role="status">Loading problem overview…</p>;
  if (!problem.data || Number(problem.data.domain_id) !== domainId) return <p role="alert">This problem is not available in this domain.</p>;
  const latest = versions.data?.items[0];
  const hasScenarios = (scenarios.data?.total ?? 0) > 0;
  const nextHref = !latest ? `${base}/model` : !hasScenarios ? `${base}/scenarios` : `${base}/runs`;
  const nextLabel = !latest ? (can("model.publish") ? "Build the model" : "View the model") : !hasScenarios ? "Review scenarios" : "Open results";
  return <div className="max-w-6xl space-y-6">
    <Link className={link} to={`/domains/${domainId}/problems`}>All problems in this domain</Link>
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold text-slate-900">{problem.data.name}</h1>
        <p className="mt-2 text-sm text-slate-600">Prepare the model, explore scenarios, and review the decisions it produces.</p>
        {problem.data.owner && <p className="mt-2 text-sm text-slate-500">Owner: {problem.data.owner}</p>}
      </div>
      <Link className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700" to={nextHref}>{nextLabel}<ArrowRight size={16} aria-hidden /></Link>
    </header>
    <section aria-label="Planning workflow" className="grid gap-4 md:grid-cols-3">
      {[
        { title: "Model", Icon: Workflow, href: "model", status: latest ? `Published version ${latest.version}` : "No published version", detail: "Define the decisions, rules and goals." },
        { title: "Scenarios", Icon: GitBranch, href: "scenarios", status: `${scenarios.data?.total ?? 0} scenarios`, detail: "Compare assumptions without changing the published model." },
        { title: "Runs & results", Icon: Play, href: "runs", status: hasScenarios ? "Ready to review or run" : "Create a scenario first", detail: "Inspect plans, feasibility and proof status. Publication does not mean a plan has been solved." },
      ].map(({ title, Icon, href, status, detail }) => <article className={card} key={href}>
        <Icon className="mb-3 h-5 w-5 text-blue-700" aria-hidden /><h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <p className="my-2 text-sm font-medium text-slate-700">{status}</p><p className="text-sm text-slate-600">{detail}</p>
        <Link className={`${link} mt-3`} to={`${base}/${href}`}>Open {title.toLowerCase()}<ArrowRight size={16} aria-hidden /></Link>
      </article>)}
    </section>
    <section className={card} aria-labelledby="scenario-overview-heading">
      <h2 id="scenario-overview-heading" className="text-lg font-semibold text-slate-900">Choose a scenario</h2>
      {hasScenarios ? <ul className="mt-3 divide-y divide-slate-100">{scenarios.data?.items.map((scenario) => <li className="flex flex-wrap items-center justify-between gap-3 py-3" key={scenario.id}>
        <Link className={link} to={`${base}/scenarios/${scenario.id}`}>{scenario.name}</Link>
        <Link className={link} to={`${base}/runs?scenario=${scenario.id}`}>Review results for {scenario.name}</Link>
      </li>)}</ul> : <p className="mt-3 text-sm text-slate-600">{latest ? "Create a scenario from a published version to prepare a run." : "Publish a model version before creating a scenario."}</p>}
      <Link className={`${link} mt-3`} to={`${base}/scenarios`}>All scenarios</Link>
    </section>
    <footer className="flex flex-wrap gap-6">
      <Link className={link} to={`${base}/versions`}>Versions & quality checks</Link>
      <Link className={link} to={`${base}/inputs`}>Inputs</Link>
      <Link className={link} to={`/domains/${domainId}/data/parameters`}>Shared input values</Link>
    </footer>
  </div>;
}
