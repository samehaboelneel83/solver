/**
 * The one unpublished model per problem that the Model editor's forms, its
 * Blocks tab and the optimization view's Edit mode all edit (Blockly edit
 * mode spec §2). The whole IR document, what it was seeded from, and when
 * it was last edited -- kept in this browser's storage so it survives a
 * reload, and never on the server until it is published.
 *
 * Shaped like `useDomain`: a tiny external store with a memory fallback for
 * storage that throws, following other tabs through `storage` events.
 */
import { useSyncExternalStore } from "react";

export type DraftBase = "scratch" | `version-${number}`;
export type ModelDraft = {
  problemId: number;
  base: DraftBase;
  /** The version number the draft started from, for "Start again from version N"; null from scratch. */
  baseVersion: number | null;
  ir: Record<string, unknown>;
  editedAt: string;
  /** False when storage refused the write: the draft lives only as long as this page. */
  persisted: boolean;
};

export const DRAFT_KEY_PREFIX = "solver_model_draft_";
const key = (problemId: number) => `${DRAFT_KEY_PREFIX}${problemId}`;

type Listener = () => void;
const listeners = new Set<Listener>();
const memory = new Map<number, ModelDraft>();
/** The last snapshot handed out per problem, and the raw text it came from:
 * `useSyncExternalStore` needs the same object back while nothing changed. */
const snapshots = new Map<number, { raw: string | null; draft: ModelDraft | null }>();

function isDraft(value: unknown): value is ModelDraft {
  if (!value || typeof value !== "object") return false;
  const draft = value as Partial<ModelDraft>;
  return (
    typeof draft.problemId === "number" &&
    (draft.base === "scratch" || (typeof draft.base === "string" && /^version-\d+$/.test(draft.base))) &&
    !!draft.ir && typeof draft.ir === "object" && !Array.isArray(draft.ir) &&
    typeof draft.editedAt === "string"
  );
}

function rawOf(problemId: number): string | null {
  try {
    return localStorage.getItem(key(problemId));
  } catch {
    return null;
  }
}

export function readDraft(problemId: number): ModelDraft | null {
  const raw = rawOf(problemId);
  const cached = snapshots.get(problemId);
  if (raw === null) {
    const inMemory = memory.get(problemId) ?? null;
    if (cached && cached.raw === null && cached.draft === inMemory) return inMemory;
    snapshots.set(problemId, { raw: null, draft: inMemory });
    return inMemory;
  }
  if (cached && cached.raw === raw) return cached.draft;
  let draft: ModelDraft | null;
  try {
    const parsed: unknown = JSON.parse(raw);
    draft = isDraft(parsed) ? { ...parsed, persisted: true } : null;
  } catch {
    draft = null;
  }
  snapshots.set(problemId, { raw, draft });
  return draft;
}

function notify() {
  listeners.forEach((listener) => listener());
}

export function writeDraft(input: { problemId: number; base: DraftBase; baseVersion: number | null; ir: Record<string, unknown> }): ModelDraft {
  const draft: ModelDraft = { ...input, editedAt: new Date().toISOString(), persisted: true };
  try {
    localStorage.setItem(key(input.problemId), JSON.stringify(draft));
    memory.delete(input.problemId);
  } catch {
    draft.persisted = false;
    memory.set(input.problemId, draft);
  }
  notify();
  return readDraft(input.problemId) ?? draft;
}

/** Apply `update` to the store's own current IR -- never to a copy a
 * component rendered from, which another tab may have replaced. */
export function updateDraftIr(
  problemId: number,
  update: (ir: Record<string, unknown>) => Record<string, unknown>
): ModelDraft | null {
  const current = readDraft(problemId);
  if (!current) return null;
  return writeDraft({ problemId, base: current.base, baseVersion: current.baseVersion, ir: update(current.ir) });
}

export function clearDraft(problemId: number): void {
  memory.delete(problemId);
  try {
    localStorage.removeItem(key(problemId));
  } catch {
    // Nothing stored, nothing to remove.
  }
  notify();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  function onStorage(event: StorageEvent) {
    if (event.key === null || event.key.startsWith(DRAFT_KEY_PREFIX)) listener();
  }
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useModelDraft(problemId: number): ModelDraft | null {
  return useSyncExternalStore(subscribe, () => readDraft(problemId), () => null);
}
