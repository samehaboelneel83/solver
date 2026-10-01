import { Link, useParams } from "react-router-dom";
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
        { title: "Database connections", description: "Import rows from a database; Excel and CSV import live on each kind of record.", to: `${domain}/data/sources`, capability: "integration.run" },
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

// Sources & imports moved to their own page (Epic UX, U-4); re-exported for the routes and tests that name it here.
export { SourcesPage } from "./Sources";
