import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

type Hub = "inputs" | "data" | "structure" | "quality" | "access";
type Card = { title: string; description: string; to: string; capability?: string };
const cardClass = "block rounded-xl border border-slate-200 bg-white p-5 hover:border-blue-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600";

/** Task-oriented entrances to existing tools; no duplicate stores or editors. */
export default function NavigationHub({ kind }: { kind: Hub }) {
  const { domainId, problemId } = useParams();
  const { can } = useCapabilities();
  const domain = `/domains/${domainId}`;
  const problem = `${domain}/problems/${problemId}`;
  const content: Record<Hub, { title: string; detail: string; cards: Card[] }> = {
    inputs: {
      title: "Inputs", detail: "Prepare shared domain data, then choose scenario assumptions. Published runs retain their recorded inputs.",
      cards: [
        { title: "Records & relationships", description: "Review the people, resources and connections used by this problem.", to: `${domain}/data` },
        { title: "Input values", description: "Review demand, capacities, costs and other shared parameters.", to: `${domain}/data/parameters` },
        { title: "Scenario inputs", description: "Choose a scenario to inspect its dataset and assumptions.", to: `${problem}/scenarios` },
        { title: "Sources & imports", description: "Review configured database connections.", to: `${domain}/data/sources`, capability: "integration.run" },
      ],
    },
    data: {
      title: "Records & relationships", detail: "Operational data is shared by the problems in this domain.",
      cards: [
        { title: "Records", description: "Manage people, places, resources and other business objects.", to: `${domain}/data/records` },
        { title: "Relationships", description: "Manage connections between records.", to: `${domain}/data/relationships` },
        { title: "Parameters", description: "Manage numeric and structured input values.", to: `${domain}/data/parameters` },
      ],
    },
    structure: {
      title: "Data structure", detail: "Define the vocabulary used by records and optimization models.",
      cards: [
        { title: "Record types", description: "Define kinds of records and their attributes.", to: `${domain}/structure/record-types` },
        { title: "Relationship types", description: "Define how kinds of records can connect.", to: `${domain}/structure/relationship-types` },
      ],
    },
    quality: {
      title: "Quality checks", detail: "Review input values and validate published models from their problem workspace. A consolidated domain quality report is not available yet.",
      cards: [
        { title: "Review input values", description: "Check parameters and missing values in the existing data editor.", to: `${domain}/data/parameters` },
        { title: "Check relationships", description: "Inspect links and their record references.", to: `${domain}/data/relationships` },
        { title: "Model validation", description: "Choose a problem, then open Versions to use its quality checks.", to: `${domain}/problems` },
      ],
    },
    access: {
      title: "Access & policies", detail: "Manage access and configuration for this installation. Available actions follow your account capabilities.",
      cards: [
        { title: "Users", description: "Manage people and role assignments.", to: "/iam/user_account", capability: "iam.manage" },
        { title: "Roles & permissions", description: "Review roles and their granted capabilities.", to: "/iam/role", capability: "iam.manage" },
        { title: "Platform settings", description: "Configure platform defaults and policies.", to: "/settings", capability: "settings.edit" },
        { title: "API keys", description: "Manage programmatic credentials.", to: "/api-keys", capability: "iam.manage" },
        { title: "Organizations", description: "Review tenant organizations.", to: "/iam/organization", capability: "domain.edit" },
        { title: "Audit", description: "Review recorded changes.", to: "/ops/audit", capability: "iam.manage" },
      ],
    },
  };
  const page = content[kind];
  useDocumentTitle(page.title);
  return <div className="max-w-5xl space-y-6">
    <header><h1 className="text-2xl font-semibold text-slate-900">{page.title}</h1>
      <p className="mt-2 text-sm text-slate-600">{page.detail}</p></header>
    <div className="grid gap-4 sm:grid-cols-2">
      {page.cards.filter(item => !item.capability || can(item.capability)).map(item =>
        <Link key={item.to} to={item.to} className={cardClass}>
          <h2 className="font-semibold text-blue-700">{item.title}</h2>
          <p className="mt-2 text-sm text-slate-600">{item.description}</p>
        </Link>)}
    </div>
    <Link className="inline-block py-2 text-sm text-blue-700 underline" to={kind === "access" ? "/help/getting-started" : problemId ? `${problem}/overview` : `${domain}/overview`}>
      {kind === "access" ? "Local help" : problemId ? "Problem overview" : "Domain overview"}
    </Link>
  </div>;
}

type Connection = { id: number; name: string; enabled: boolean };
export function SourcesPage() {
  const { domainId } = useParams();
  const { can, known } = useCapabilities();
  useDocumentTitle("Sources & imports");
  if (!known) return <p role="status">Checking access…</p>;
  if (!can("integration.run")) return <p role="alert">Your account does not have access to sources and imports.</p>;
  return <SourceList key={domainId} domainId={domainId!} />;
}

function SourceList({ domainId }: { domainId: string }) {
  const [page, setPage] = useState(0);
  const sources = useQuery({
    queryKey: ["connections", domainId, page],
    queryFn: () => apiFetch<{ items: Connection[]; total: number }>(`/api/v1/connections?domain_id=${domainId}&limit=20&offset=${page * 20}`),
  });
  return <div className="max-w-5xl space-y-5">
    <h1 className="text-2xl font-semibold">Sources & imports</h1>
    <p className="text-sm text-slate-600">Configured database sources for this domain. Connection setup and extraction remain available through the local integration API; the import wizard is not available yet.</p>
    {sources.isError ? <div role="alert">Sources could not be loaded. <button className="p-2 text-blue-700 underline" onClick={() => void sources.refetch()}>Retry</button></div>
      : sources.fetchStatus === "paused" ? <p role="status">Waiting for a connection to the server.</p>
      : sources.isLoading ? <p role="status">Loading sources…</p>
      : sources.data?.items.length ? <ul className="divide-y rounded-xl border border-slate-200 bg-white">{sources.data.items.map(source =>
        <li key={source.id} className="flex justify-between gap-4 p-4"><span>{source.name}</span><span>{source.enabled ? "Enabled" : "Disabled"}</span></li>)}</ul>
      : <p>No configured sources on this page.</p>}
    <nav aria-label="Source pages" className="flex items-center gap-4">
      <button className="p-2 disabled:opacity-50" disabled={page === 0 || sources.isLoading} onClick={() => setPage(page - 1)}>Previous</button>
      <span>Page {page + 1}</span>
      <button className="p-2 disabled:opacity-50" disabled={!sources.data || (page + 1) * 20 >= sources.data.total} onClick={() => setPage(page + 1)}>Next</button>
    </nav>
    <Link className="inline-block py-2 text-blue-700 underline" to="/help/api">Local API reference</Link>
  </div>;
}
