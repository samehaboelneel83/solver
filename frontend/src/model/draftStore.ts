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
import { getToken } from "../api/client";

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
// JWT subject is a browser namespace, not an authorization decision.
// Server permissions still govern every model read and publication.
const unknownSessions = new Map<string, string>();
export function draftStorageKey(problemId: number): string {
  let owner = "signed-out";
  const token = getToken();
  if (token) {
    try {
      const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const claims = JSON.parse(atob(payload));
      if (typeof claims.sub !== "string" || !claims.sub) throw new Error("Missing subject");
      owner = `user:${encodeURIComponent(claims.sub)}`;
    } catch {
      if (!unknownSessions.has(token)) unknownSessions.set(token, crypto.randomUUID());
      owner = `session:${unknownSessions.get(token)}`;
    }
  }
  return `${DRAFT_KEY_PREFIX}v2:${owner}:${problemId}`;
}
const key = draftStorageKey;

export function hasLegacyDraft(problemId: number): boolean {
  try { return localStorage.getItem(`${DRAFT_KEY_PREFIX}${problemId}`) !== null; }
  catch { return false; }
}

type Listener = () => void;
const listeners = new Set<Listener>();
const memory = new Map<string, ModelDraft>();
type History = { past: ModelDraft[]; future: ModelDraft[]; current: ModelDraft };
const histories = new Map<string, History>();
const HISTORY_LIMIT = 30;
let replaying = false;
const sameDraft = (a: ModelDraft | null, b: ModelDraft | null) => JSON.stringify(a) === JSON.stringify(b);
/** The last snapshot handed out per problem, and the raw text it came from:
 * `useSyncExternalStore` needs the same object back while nothing changed. */
const snapshots = new Map<string, { raw: string | null; draft: ModelDraft | null }>();

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
  if (memory.has(key(problemId))) return memory.get(key(problemId))!;
  const raw = rawOf(problemId);
  const cached = snapshots.get(key(problemId));
  if (raw === null) {
    const inMemory = memory.get(key(problemId)) ?? null;
    if (cached && cached.raw === null && cached.draft === inMemory) return inMemory;
    snapshots.set(key(problemId), { raw: null, draft: inMemory });
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
  snapshots.set(key(problemId), { raw, draft });
  return draft;
}

function notify() {
  listeners.forEach((listener) => listener());
}

export function writeDraft(input: { problemId: number; base: DraftBase; baseVersion: number | null; ir: Record<string, unknown> }, previousIr?: Record<string, unknown>): ModelDraft {
  const previous = readDraft(input.problemId) ?? (previousIr ? { ...input, ir: previousIr, editedAt: new Date().toISOString(), persisted: false } : null);
  const draft: ModelDraft = { ...input, editedAt: new Date().toISOString(), persisted: true };
  try {
    localStorage.setItem(key(input.problemId), JSON.stringify(draft));
    memory.delete(key(input.problemId));
  } catch {
    draft.persisted = false;
    memory.set(key(input.problemId), draft);
  }
  const saved = readDraft(input.problemId) ?? draft;
  if (!replaying) {
    const history = histories.get(key(input.problemId));
    const continuous = history && sameDraft(previous, history.current) && previous?.base === saved.base;
    histories.set(key(input.problemId), {
      past: previous && previous.base === saved.base
        ? [...(continuous ? history.past : []), previous].slice(-HISTORY_LIMIT) : [],
      future: [], current: saved,
    });
  }
  notify();
  return saved;
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
  histories.delete(key(problemId));
  memory.delete(key(problemId));
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
    if (event.key === null || event.key === "solver_token" || event.key.startsWith(DRAFT_KEY_PREFIX)) {
      // A different tab may have replaced the draft. Never replay history over it.
      histories.clear();
      listener();
    }
  }
  window.addEventListener("storage", onStorage);
  window.addEventListener("solver-auth-changed", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("solver-auth-changed", listener);
  };
}

export function useModelDraft(problemId: number): ModelDraft | null {
  return useSyncExternalStore(subscribe, () => readDraft(problemId), () => null);
}


export function draftHistory(problemId: number): { canUndo: boolean; canRedo: boolean } {
  const history = histories.get(key(problemId));
  if (!history || !sameDraft(readDraft(problemId), history.current)) return { canUndo: false, canRedo: false };
  return { canUndo: history.past.length > 0, canRedo: history.future.length > 0 };
}

export function replayDraft(problemId: number, direction: "undo" | "redo"): boolean {
  const history = histories.get(key(problemId));
  const allowed = draftHistory(problemId);
  if (!history || !(direction === "undo" ? allowed.canUndo : allowed.canRedo)) return false;
  const source = direction === "undo" ? history.past : history.future;
  const target = source[source.length - 1];
  const previous = history.current;
  replaying = true;
  try {
    history.current = writeDraft({ problemId, base: target.base, baseVersion: target.baseVersion, ir: target.ir });
    source.pop();
    (direction === "undo" ? history.future : history.past).push(previous);
  } finally { replaying = false; }
  notify();
  return true;
}
