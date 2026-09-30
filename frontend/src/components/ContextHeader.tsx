import { useDomains, useDomainDetail } from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { apiFetch } from "../api/client";
import { parseRouteId } from "../lib/routeId";
import { useWords } from "../lib/words";

/**
 * Visible domain context for the shell header (OAAS N03 §3.6).
 * Domain name stays visible even when the sidebar is collapsed.
 */
export default function ContextHeader() {
  const { domainId } = useDomain();
  const { data } = useDomains();
  const { pathname, search } = useLocation();
  const pathProblem = pathname.match(/^\/domains\/[^/]+\/problems\/([^/]+)(?:\/|$)/);
  const problemId = parseRouteId(pathProblem ? pathProblem[1] : new URLSearchParams(search).get("problem"));
  const w = useWords();
  const problem = useQuery({
    queryKey: ["entities", "public", "problem", problemId],
    queryFn: () => apiFetch<{ id: number; domain_id: number; name: string }>(`/api/problem/${problemId}`),
    enabled: problemId !== null && domainId !== null,
  });
  const domains = Array.isArray(data?.items) ? data.items : [];
  const listed = domains.find((row) => row.id === domainId);
  const detail = useDomainDetail(data && !listed ? domainId : null);
  const domain = listed ?? (detail.data?.id === domainId ? detail.data : undefined);

  if (!domain) {
    return (
      <p className="truncate text-xs text-slate-500" data-testid="context-header">
        No {w("domain")} selected
      </p>
    );
  }

  return (
    <p className="min-w-0 max-w-[24rem] truncate text-xs text-slate-600" data-testid="context-header" title={domain.name}>
      {w("Domain")}: <span className="font-medium text-slate-800">{domain.name}</span>
      {problem.data && Number(problem.data.domain_id) === domainId && (
        <> / Problem: <span className="font-medium text-slate-800">{problem.data.name}</span></>
      )}
    </p>
  );
}
