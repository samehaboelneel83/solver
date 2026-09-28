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
function draftOwner(): string {
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
  return owner;
}
export function draftStorageKey(problemId: number): string {
  return `${DRAFT_KEY_PREFIX}v2:${draftOwner()}:${problemId}`;
}
const key = draftStorageKey;

const legacyKey = (problemId: number) => `${DRAFT_KEY_PREFIX}${problemId}`;
const legacyClaimKey = (problemId: number) => `${DRAFT_KEY_PREFIX}legacy-claim:${problemId}`;

export function hasLegacyDraft(problemId: number): boolean {
  try { return localStorage.getItem(legacyKey(problemId)) !== null; }
  catch { return false; }
}

/**
 * Where an unscoped (pre-account) draft stands for the signed-in account.
 * The browser never recorded who wrote it, so recovery is an explicit claim
 * by one signed-in account; the original entry is never modified or removed.
 */
export type LegacyDraftStatus = "none" | "unreadable" | "available" | "signed-out" | "claimed-by-you" | "claimed-by-other";

function legacyClaimOwner(problemId: number): string | null {
  try {
    const claim: unknown = JSON.parse(localStorage.getItem(legacyClaimKey(problemId)) ?? "null");
    return claim && typeof claim === "object" && typeof (claim as { owner?: unknown }).owner === "string"
      ? (claim as { owner: string }).owner : null;
  } catch { return null; }
}

function readLegacyDraft(problemId: number): Omit<ModelDraft, "persisted"> | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(legacyKey(problemId)) ?? "null");
    if (!isDraft(parsed) || parsed.problemId !== problemId) return null;
    const baseVersion = typeof parsed.baseVersion === "number" && Number.isInteger(parsed.baseVersion) ? parsed.baseVersion : null;
    return { problemId, base: parsed.base, baseVersion, ir: parsed.ir, editedAt: parsed.editedAt };
  } catch { return null; }
}

export function legacyDraftStatus(problemId: number): LegacyDraftStatus {
  if (!hasLegacyDraft(problemId)) return "none";
  const claimedBy = legacyClaimOwner(problemId);
  const owner = draftOwner();
  if (claimedBy) return claimedBy === owner ? "claimed-by-you" : "claimed-by-other";
  if (!owner.startsWith("user:")) return "signed-out";
  return readLegacyDraft(problemId) ? "available" : "unreadable";
}

/**
 * Copy an unscoped draft into the signed-in account's draft, once, on that
 * account's explicit request. Refuses to overwrite the account's own draft,
 * and records the claim so no other account in this browser can recover it
 * afterwards. The original entry stays untouched as the source backup.
 */
export function claimLegacyDraft(problemId: number): ModelDraft {
  const status = legacyDraftStatus(problemId);
  if (status === "claimed-by-other") throw new Error("Another account in this browser has already recovered this draft.");
  if (status === "claimed-by-you") throw new Error("You have already recovered this draft.");
  if (status === "signed-out") throw new Error("Sign in with a named account to recover this draft.");
  const legacy = status === "available" ? readLegacyDraft(problemId) : null;
  if (!legacy) throw new Error("The older draft could not be read, so it cannot be recovered here. It remains preserved in this browser.");
  if (readDraft(problemId)) throw new Error("Publish or discard your current unpublished draft before recovering the older one.");
  try {
    localStorage.setItem(legacyClaimKey(problemId), JSON.stringify({ owner: draftOwner(), claimedAt: new Date().toISOString() }));
  } catch {
    throw new Error("This browser's storage refused the recovery. Free some space and try again; nothing was changed.");
  }
  const saved = writeDraft({ problemId, base: legacy.base, baseVersion: legacy.baseVersion, ir: legacy.ir });
  if (!saved.persisted) {
    // A memory-only copy would be lost on reload while the claim blocks a retry.
    try { localStorage.removeItem(legacyClaimKey(problemId)); } catch { /* claim was never kept */ }
  }
  return saved;
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
