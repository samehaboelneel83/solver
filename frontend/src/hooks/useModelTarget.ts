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
  /** Explicit URL asked for a problem that is not in this domain (or gone). */
  problemMissing: boolean;
  /** Explicit URL asked for a version that is not on the resolved problem. */
  versionMissing: boolean;
};

/**
 * Which problem and which of its model versions the optimization view draws.
 *
 * When the URL (or caller) names a problem or version explicitly and it does
 * not resolve, we do **not** silently substitute another object (OAAS N02).
 * Defaults apply only when nothing was requested.
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

  const explicitProblem = requested.problemId !== null;
  const matchedProblem = problemItems.find((row) => row.id === requested.problemId);
  const problemMissing = explicitProblem && !problems.isLoading && matchedProblem === undefined;
  const problemId = explicitProblem
    ? (matchedProblem?.id ?? null)
    : (problemItems[0]?.id ?? null);

  const versions = useVersions(enabled ? problemId : null, { limit: 500 });
  const versionItems = [...(versions.data?.items ?? [])].sort((a, b) => b.version - a.version);
  const explicitVersion = requested.versionId !== null;
  const matchedVersion = versionItems.find((row) => row.id === requested.versionId);
  const versionMissing =
    explicitVersion && problemId !== null && !versions.isLoading && matchedVersion === undefined;
  const versionId = explicitVersion
    ? (matchedVersion?.id ?? null)
    : (versionItems[0]?.id ?? null);

  return {
    problemId,
    versionId,
    problems: problemItems,
    versions: versionItems,
    isLoading: problems.isLoading || (problemId !== null && versions.isLoading),
    problemMissing,
    versionMissing,
  };
}
