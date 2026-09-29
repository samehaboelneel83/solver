import { Navigate, useLocation, useParams } from "react-router-dom";
import { useEntity } from "../api/entities";
import { useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";
import LoadFailure from "./LoadFailure";

/**
 * An old, unscoped link landing on its canonical page in one step (Epic UX, U-1).
 *
 * Old pages read their context from the query (`/runs?problem=7&run=12`) or from the
 * domain chosen last. Where that context is known the link goes straight to the scoped
 * page (`/domains/3/problems/7/runs/12`), keeping the rest of the query and the hash;
 * where it is not, the old page still opens with its own pickers, so no bookmark breaks.
 */

/** Old problem pages: the page segment and the query key whose id becomes a path segment. */
export const PROBLEM_PAGES: Record<string, string | null> = {
  model: null,
  versions: "version",
  scenarios: "scenario",
  runs: "run",
  workspace: "run",
  inputs: null,
};

/** Old domain pages and where they live now. */
export const DOMAIN_PAGES: Record<string, string> = {
  "entity-types": "structure/record-types",
  "relationship-types": "structure/relationship-types",
  entities: "data/records",
  relationships: "data/relationships",
  parameters: "data/parameters",
  graph: "data/explore",
  data: "data",
  structure: "structure",
  sources: "data/sources",
  quality: "data/quality",
};

function rest(search: URLSearchParams, drop: string[]): string {
  const next = new URLSearchParams(search);
  for (const key of drop) next.delete(key);
  const text = next.toString();
  return text ? `?${text}` : "";
}

/** `/model`, `/versions`, `/scenarios`, `/runs`, `/workspace` with `?problem=`. */
export function LegacyProblemRedirect({ page, fallback }: { page: string; fallback: JSX.Element }) {
  const location = useLocation();
  const search = new URLSearchParams(location.search);
  const problemId = parseRouteId(search.get("problem"));
  const problem = useEntity("public", "problem", problemId === null ? undefined : String(problemId));
  if (problemId === null) return fallback;
  if (problem.isError) {
    return <LoadFailure subject="The linked problem" error={problem.error} retry={() => void problem.refetch()}
      back={{ label: "Choose a domain", to: "/domains" }} />;
  }
  if (!problem.data) return <p role="status">Opening the problem…</p>;
  const key = PROBLEM_PAGES[page];
  const id = key ? parseRouteId(search.get(key)) : null;
  const target = page === "workspace" ? "runs" : page;
  const path = `/domains/${Number(problem.data.domain_id)}/problems/${problemId}/${target}${id !== null ? `/${id}` : ""}`;
  const drop = ["problem", "domain", ...(id !== null && key ? [key] : [])];
  let query = rest(search, drop);
  if (page === "workspace") query = query ? `${query}&tab=guided` : "?tab=guided";
  return <Navigate to={`${path}${query}${location.hash}`} replace />;
}

/** The old domain pages (`/parameters`, `/entities/5`, `/data`, …): `?domain=`, else the domain chosen last. */
export function LegacyDomainRedirect({ page, fallback }: { page: string; fallback?: JSX.Element }) {
  const location = useLocation();
  const params = useParams();
  const { domainId: chosen } = useDomain();
  const search = new URLSearchParams(location.search);
  const domainId = parseRouteId(search.get("domain")) ?? chosen;
  if (domainId === null) {
    // A hub with no domain yet: the chooser, which comes back to this hub.
    return fallback ?? <Navigate to={`/domains?next=${encodeURIComponent(DOMAIN_PAGES[page])}`} replace />;
  }
  const id = params.id ? `/${params.id}` : location.pathname.endsWith("/new") ? "/new" : "";
  return <Navigate to={`/domains/${domainId}/${DOMAIN_PAGES[page]}${id}${rest(search, ["domain"])}${location.hash}`} replace />;
}
