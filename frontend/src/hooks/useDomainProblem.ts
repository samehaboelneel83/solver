/**
 * The problem a page is about, in a domain of any size (plan §4.2): the first
 * page of the domain's problems for the picker, and a requested problem that
 * is not on that page fetched by its id and checked to belong to the domain.
 * A deep link therefore never depends on which page a problem falls on, and
 * a problem from another domain is reported, never substituted.
 */
import { useEntity, useEntityList } from "../api/entities";
import { ApiError } from "../api/client";
import { PROBLEM_PAGE } from "../components/ProblemPicker";
import { parseRouteId } from "../lib/routeId";

type Row = Record<string, unknown>;

export type DomainProblem =
  | { state: "loading" }
  | { state: "offline" }
  | { state: "failed"; subject: string; error: unknown; retry: () => void }
  | { state: "mismatch" }
  | { state: "empty" }
  | { state: "ready"; problem: Row; firstPage: Row[]; total: number };

/** `raw` is the requested id as the URL gave it; null or undefined chooses the first problem. */
export function useDomainProblem(domainId: string | number, raw: string | null | undefined): DomainProblem {
  const problems = useEntityList("public", "problem", {
    limit: PROBLEM_PAGE,
    offset: 0,
    orderBy: "name",
    order: "asc",
    filters: { domain_id: String(domainId) },
  });
  const requested = parseRouteId(raw);
  const listed = problems.data?.items ?? [];
  const needsDetail = requested !== null && !listed.some((row) => Number(row.id) === requested);
  const detail = useEntity("public", "problem", needsDetail ? String(requested) : undefined);
  const extra = detail.data && Number(detail.data.domain_id) === Number(domainId) && Number(detail.data.id) === requested
    ? detail.data : undefined;

  const invalid = raw !== null && raw !== undefined && requested === null;
  if (invalid || (needsDetail && detail.data && !extra)
    || (needsDetail && detail.error instanceof ApiError && detail.error.status === 404)) {
    return { state: "mismatch" };
  }
  if (needsDetail && detail.isError) {
    return { state: "failed", subject: "The requested problem", error: detail.error, retry: () => { void detail.refetch(); } };
  }
  if (problems.isError) {
    return { state: "failed", subject: "The problem list", error: problems.error, retry: () => { void problems.refetch(); } };
  }
  if ((problems.fetchStatus === "paused" && !problems.data) || (needsDetail && detail.fetchStatus === "paused" && !detail.data)) {
    return { state: "offline" };
  }
  if (problems.isLoading || (needsDetail && detail.isLoading) || problems.isPlaceholderData) return { state: "loading" };

  const items = needsDetail && extra ? [...listed, extra] : listed;
  if (items.length === 0) return { state: "empty" };
  const problem = requested === null ? items[0] : items.find((row) => Number(row.id) === requested);
  if (!problem) return { state: "mismatch" };
  return { state: "ready", problem, firstPage: listed, total: problems.data?.total ?? listed.length };
}
