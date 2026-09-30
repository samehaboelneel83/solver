import LoadFailure from "../components/LoadFailure";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Database, FileStack, GitBranch, Play } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import { publishDraft, solveProblem, useDomains, useDomainDetail, useReadiness } from "../api/v1";
import MissingValues from "../components/MissingValues";
import { missingOf, nextAction, problemSteps, type StepKey, type StepState } from "../lib/problemSteps";
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
          <p className="mt-2 text-sm text-slate-500" aria-live="polite">{problems.data?.total ?? 0} {(problems.data?.total ?? 0) === 1 ? "problem" : "problems"}{q ? " matching your search" : " in this domain"}</p>
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

const MARK: Record<StepState, { text: string; style: string; words: string }> = {
  done: { text: "✓", style: "bg-emerald-100 text-emerald-800", words: "done" },
  todo: { text: "•", style: "bg-blue-100 text-blue-800", words: "to do" },
  fix: { text: "!", style: "bg-rose-100 text-rose-700", words: "something to fix" },
  wait: { text: "…", style: "bg-slate-100 text-slate-500", words: "waiting" },
};

const primary = "inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50";
const secondary = "inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50";

/**
 * A problem from one place (simplification plan, phase 1): five steps --
 * Data, Model, Check, Solve, Results -- each saying whether it is done, and
 * one button for what to do next. Missing values are filled in right here,
 * and Solve keeps the "Base" scenario on the latest version by itself;
 * scenarios, versions and inputs stay one link away for what-if work.
 */
export function ProblemOverview() {
  const params = useParams();
  const domainId = parseRouteId(params.domainId ?? null);
  const problemId = parseRouteId(params.problemId ?? null);
  const readiness = useReadiness(problemId);
  const { can } = useCapabilities();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);
  useDocumentTitle(`${readiness.data?.problem.name ?? "Problem"} · Overview`);
  const base = `/domains/${domainId}/problems/${problemId}`;
  const solve = useMutation({
    mutationFn: async (publishFirst: boolean) => {
      const draft = readiness.data?.draft;
      if (publishFirst && draft) await publishDraft(problemId as number, draft.revision, "Published from the problem page to solve");
      return solveProblem(problemId as number);
    },
    onSuccess: (run) => {
      void client.invalidateQueries();
      navigate(`${base}/runs/${run.id}`);
    },
    onError: (error: unknown) => setFailure(formatApiError(error)),
  });
  if (readiness.isError) return <LoadFailure subject="The problem overview" error={readiness.error} retry={() => void readiness.refetch()} />;
  if (readiness.isLoading || !readiness.data) return <p role="status">Loading problem overview…</p>;
  const data = readiness.data;
  if (Number(data.problem.domain_id) !== domainId) return <p role="alert">This problem is not available in this domain.</p>;

  const steps = problemSteps(data);
  const next = nextAction(data, can("model.publish"));
  const mayRun = can("run.submit");
  const solveNow = (publishFirst = false) => { setFailure(null); solve.mutate(publishFirst); };
  const jump = (key: StepKey) => document.getElementById(`step-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const nextButton = (() => {
    switch (next.kind) {
      case "build": return <Link className={primary} to={`${base}/model`}>{can("model.publish") ? "Build the model" : "View the model"}<ArrowRight size={16} aria-hidden /></Link>;
      case "publish-and-solve": return <button type="button" className={primary} disabled={!mayRun || solve.isPending} onClick={() => solveNow(true)}>{solve.isPending ? "Publishing…" : "Publish changes and solve"}<Play size={16} aria-hidden /></button>;
      case "fill": return <button type="button" className={primary} onClick={() => jump("data")}>Fill in {next.count} missing {next.count === 1 ? "value" : "values"}<ArrowRight size={16} aria-hidden /></button>;
      case "fix": return <button type="button" className={primary} onClick={() => jump("check")}>See what stops it<ArrowRight size={16} aria-hidden /></button>;
      case "follow": return <Link className={primary} to={`${base}/runs/${next.runId}`}>Follow the run<ArrowRight size={16} aria-hidden /></Link>;
      case "results": return <Link className={primary} to={`${base}/runs/${next.runId}`}>See the results<ArrowRight size={16} aria-hidden /></Link>;
      case "solve": return <button type="button" className={primary} disabled={!mayRun || solve.isPending} onClick={() => solveNow()}>{solve.isPending ? "Starting…" : "Solve"}<Play size={16} aria-hidden /></button>;
    }
  })();

  const detail = (key: StepKey) => {
    if (key === "data") return <>
      {missingOf(data).map((finding) => finding.missing && (
        // Keyed by what is missing, not by the count in the words: a save changes the count,
        // and the table (with anything typed in it) must stay.
        <div key={`${finding.missing.set}.${finding.missing.attribute}`} className="mt-2 text-sm text-rose-900">{finding.says}
          <MissingValues gap={finding.missing} domainId={domainId as number} />
        </div>
      ))}
      <Link className={link} to={`/domains/${domainId}/data/records`}>Open the records</Link>
    </>;
    if (key === "model") return <div className="flex flex-wrap items-center gap-3">
      <Link className={link} to={`${base}/model`}>Open the model</Link>
      {data.draft?.unpublished && data.latest_version && can("model.publish") && mayRun && (
        <>
          <button type="button" className={secondary} disabled={solve.isPending} onClick={() => solveNow(true)}>Publish changes and solve</button>
          <button type="button" className={secondary} disabled={solve.isPending || !data.check?.ready} onClick={() => solveNow()}>
            Solve version {data.latest_version.version} as published
          </button>
        </>
      )}
    </div>;
    if (key === "check") {
      const shown = (data.check?.findings ?? []).filter((f) => f.code !== "missing_values");
      return shown.length > 0 ? <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
        {shown.map((f) => <li key={f.code + f.says} className={f.kind === "blocker" ? "text-rose-900" : "text-amber-900"}>{f.says}</li>)}
      </ul> : null;
    }
    if (key === "solve") return <div className="flex flex-wrap items-center gap-3">
      {data.check?.ready && mayRun && next.kind !== "solve" && next.kind !== "publish-and-solve" && (
        <button type="button" className={secondary} disabled={solve.isPending} onClick={() => solveNow()}>{data.last_run ? "Solve again" : "Solve"}</button>
      )}
      <span className="text-sm text-slate-600">{data.workers.says}.</span>
    </div>;
    return data.last_run ? <Link className={link} to={`${base}/runs/${data.last_run.id}`}>Open run {String(data.last_run.id)}</Link> : null;
  };

  return <div className="max-w-4xl space-y-6">
    <Link className={link} to={`/domains/${domainId}/problems`}>All problems in this domain</Link>
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold text-slate-900">{data.problem.name}</h1>
        <p className="mt-2 text-sm text-slate-600">Data, the model, a check, a solve and its results: each step below says where it stands.</p>
      </div>
      <div className="flex flex-col items-end gap-1">
        {nextButton}
        <span className="text-xs text-slate-500">Next step</span>
      </div>
    </header>
    {failure && <p role="alert" className="rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">{failure}</p>}
    <ol aria-label="Steps" className="space-y-3">
      {steps.map((step, i) => {
        const mark = MARK[step.state];
        return <li key={step.key} id={`step-${step.key}`} className={card} aria-label={`Step ${i + 1}, ${step.title}: ${mark.words}`}>
          <div className="flex items-start gap-3">
            <span aria-hidden="true" className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${mark.style}`}>{mark.text}</span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-slate-900">{i + 1}. {step.title}</h2>
              <p className="text-sm text-slate-700" data-testid={`step-${step.key}-says`}>{step.says}</p>
              {detail(step.key)}
            </div>
          </div>
        </li>;
      })}
    </ol>
    <section className={card} aria-labelledby="more-heading">
      <h2 id="more-heading" className="text-base font-semibold text-slate-900">More</h2>
      <p className="mt-1 text-sm text-slate-600">For what-if work: other scenarios, earlier versions and every input.</p>
      <div className="mt-2 flex flex-wrap gap-6">
        <Link className={link} to={`${base}/scenarios`}>Scenarios</Link>
        <Link className={link} to={`${base}/versions`}>Versions & quality checks</Link>
        <Link className={link} to={`${base}/runs`}>All runs</Link>
        <Link className={link} to={`${base}/inputs`}>Inputs</Link>
      </div>
    </section>
  </div>;
}
