import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useVersions, type Id, type ModelVersionSummary } from "../api/v1";

export type ProblemOption = { id: Id; name: string };

/** What the optimization view is drawing, as asked for: null means "the
 * first problem" and "the latest version" respectively. */
export type ModelTargetRequest = { problemId: Id | null; versionId: Id | null };

export type ModelTarget = {
  problemId: Id | null;
  versionId: Id | null;
  problems: ProblemOption[];
  versions: ModelVersionSummary[];
  isLoading: boolean;
};

/**
 * Which problem and which of its model versions the optimization view draws.
 *
 * A request that no longer resolves -- a problem from another domain left in
 * the URL, a version since deleted -- falls back to the defaults rather than
 * drawing nothing: the first problem by name, and its latest version, which
 * is the one a person means by "the model" unless they say otherwise.
 *
 * Fetches only while `enabled`, so the two other views pay nothing for it.
 */
export function useModelTarget(domainId: Id | null, requested: ModelTargetRequest, enabled: boolean): ModelTarget {
  const problems = useQuery({
    queryKey: ["model-target", "problems", domainId],
    queryFn: () =>
      apiFetch<{ items: { id: Id; name: string }[] }>(
        `/api/problem/?limit=500&offset=0&order_by=name&order=asc&f_domain_id=${domainId}`
      ),
    enabled: enabled && domainId !== null,
  });
  const problemItems: ProblemOption[] = (problems.data?.items ?? []).map((row) => ({
    id: Number(row.id),
    name: String(row.name),
  }));
  const problemId =
    problemItems.find((row) => row.id === requested.problemId)?.id ?? problemItems[0]?.id ?? null;

  const versions = useVersions(enabled ? problemId : null, { limit: 500 });
  const versionItems = [...(versions.data?.items ?? [])].sort((a, b) => b.version - a.version);
  const versionId =
    versionItems.find((row) => row.id === requested.versionId)?.id ?? versionItems[0]?.id ?? null;

  return {
    problemId,
    versionId,
    problems: problemItems,
    versions: versionItems,
    isLoading: problems.isLoading || (problemId !== null && versions.isLoading),
  };
}
