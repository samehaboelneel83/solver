/**
 * Server-saved drafts (`backend/app/api/drafts.py`): one per person per
 * problem, saved with the revision it was built on so a save from a stale
 * tab or browser is refused (409) instead of overwriting newer work.
 */
import { ApiError, apiFetch } from "./client";

export type ServerDraft = {
  id: number;
  problem_id: number;
  base_version_id: number | null;
  base_version: number | null;
  ir: Record<string, unknown>;
  revision: number;
  created_at: string;
  updated_at: string;
};

function isServerDraft(value: unknown): value is ServerDraft {
  const draft = value as Partial<ServerDraft> | null;
  return !!draft && typeof draft === "object" && Number.isInteger(draft.revision) && draft.revision! >= 1
    && !!draft.ir && typeof draft.ir === "object" && !Array.isArray(draft.ir)
    && typeof draft.updated_at === "string";
}

const draftPath = (problemId: number) => `/api/v1/problems/${problemId}/draft`;

/** The caller's server draft for this problem, or null when there is none. */
export async function fetchServerDraft(problemId: number): Promise<ServerDraft | null> {
  try {
    const draft = await apiFetch<unknown>(draftPath(problemId));
    if (!isServerDraft(draft)) throw new Error("The server returned an unreadable draft.");
    return draft;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function saveServerDraft(
  problemId: number,
  body: { ir: Record<string, unknown>; base_version_id: number | null; expected_revision: number | null },
): Promise<ServerDraft> {
  return apiFetch<ServerDraft>(draftPath(problemId), { method: "PUT", body: JSON.stringify(body) });
}

export function discardServerDraft(problemId: number, expectedRevision: number): Promise<void> {
  return apiFetch<void>(`${draftPath(problemId)}?expected_revision=${expectedRevision}`, { method: "DELETE" });
}

/** Publish exactly `expectedRevision`. Retries must reuse `idempotencyKey`,
 * so a publish whose response was lost is answered with the same version. */
export function publishServerDraft(
  problemId: number,
  body: { expected_revision: number; note: string | null },
  idempotencyKey: string,
): Promise<{ id: number; version: number }> {
  return apiFetch(`${draftPath(problemId)}/publish`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/** The draft store's `base` for a server draft. */
export function baseOfServerDraft(draft: ServerDraft): "scratch" | `version-${number}` {
  return draft.base_version_id === null ? "scratch" : `version-${draft.base_version_id}`;
}
