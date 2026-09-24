# Blockly Edit Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Execution method chosen: native** (superpowers:executing-plans).

**Goal:** A planner builds and changes the whole model by snapping Blockly blocks together — in the Model editor's Blocks tab and in the optimization view's Edit mode — over one shared draft, publishing the same valid IR the forms publish.

**Architecture:** The draft IR is the only truth (spec approach A). A small external store (`draftStore.ts`, `localStorage`-backed, `useSyncExternalStore`) holds at most one draft per problem; the forms read and write it through a projection, the blocks through two pure conversions — `irToBlocks(ir)` (IR → Blockly serialisation JSON) and `blocksToIr(json)` (the inverse, returning the IR *and* a map from block id to the IR location it produced). Blocks read what they may offer (entity types, parameters, relationships, the declarations above them, the indices bound around them) from a per-workspace catalogue and from their own ancestors, so a dropdown only ever offers admissible choices.

**Tech Stack:** React 18, TypeScript, Blockly 12 (`zelos` renderer), Vitest + jsdom (Blockly runs headless there — spiked 2026-09-24: custom blocks with dynamic dropdown slots saved as `extraState`, loaded, edited through the API, connected and saved), FastAPI for one thin validate route, Playwright + system Chrome for the live check.

**Spec:** `docs/superpowers/specs/2026-09-24-blockly-edit-mode-design.md`

## Global Constraints

- The draft IR is the only truth; block positions are not saved (auto-laid out).
- At most one draft per problem, the **whole IR document** (every top-level key, `relationships` and `version` included) plus what it was seeded from; kept in `localStorage`, every access in try/catch, pages work without storage.
- A draft seeded from another version is never swapped silently: **Continue the draft** / **Start again from version N**.
- Publish validates, posts a new version (`createVersion`), clears the draft; Discard clears it after an inline confirmation (no `window.confirm`). Both pages show "Unpublished changes · edited HH:MM".
- Validation on every change: `checkIrShape` at once; the server's domain check debounced to 500 ms. Publish is disabled while anything is refused, and says why.
- One block per IR construct; a choice is a dropdown, never free text where a choice exists; index slots offer only indices bound, at that point, to the set the declaration expects in that position.
- **An incomplete block is not dropped:** an empty value input becomes `{"const": null}` (refused as `const_not_a_number` at that location); an unchosen dropdown is `""` (refused by the name rules).
- **The round trip is exact:** every valid IR in `backend/tests/ir_fixtures.json` and every template → `blocksToIr(irToBlocks(ir))` → deep-equal, up to exactly two canonicalisations, stated once in the test: `relationships` compared as a set, and `objective.mode: "weighted"` ≡ absent.
- The forms remain the keyboard- and screen-reader-accessible path; both pages say so beside the Blocks tab / Edit toggle.
- Names the platform uses are `^[a-z][a-z0-9_]*$`; Blockly's own undo/redo (Ctrl+Z / Ctrl+Shift+Z).

## Review Focus

1. **A block dropped outside the model root** (dragged off the rule stack onto empty canvas) — the person expects it not to vanish from the model silently: Publish is refused, naming how many blocks are outside the model. (Task 8, `blocksToIr` reports `outside: number`.)
2. **A declaration deleted while a rule still reads it** — the reading block keeps showing the stale name (not a blank or a crash), and the refusal (`reference_undeclared`) lands on that block. (Task 3 option generators keep the current value; Task 8 maps the refusal.)
3. **The same draft edited in two tabs** — the other tab follows the new draft rather than writing its stale copy back on its next keystroke. (Task 1: the store re-reads on `storage` events and every write starts from the store's current value.)
4. **Storage that throws** (private window, quota full) — editing continues in memory and the badge says the changes will not survive a reload. (Task 1 memory fallback; Task 2 badge text.)
5. **An IR whose values are outside today's dropdown options** — a set whose entity type was renamed, a parameter since deleted — loads showing those values and round-trips exactly. (Task 3 option generators always include the current value; Task 4 round-trip test with an empty catalogue.)

---

## File Structure

```
frontend/src/model/draftStore.ts            the shared draft: read/write/clear/useModelDraft (Task 1)
frontend/src/model/draftStore.test.ts
frontend/src/model/draftIr.ts                projection between the IR and the forms' structured draft (Task 2)
frontend/src/model/draftIr.test.ts
frontend/src/model/DraftBar.tsx              badge, Publish, Discard with inline confirm, Continue/Start again (Task 2)
frontend/src/pages/ModelEditor.tsx           onto the store; Forms | Blocks tabs (Tasks 2, 5)
frontend/src/lib/irBlocks/catalogue.ts       what a workspace may offer + the scope at a block (Task 3)
frontend/src/lib/irBlocks/vocabulary.ts      every block type, registered once (Tasks 3, 6)
frontend/src/lib/irBlocks/toBlocks.ts        irToBlocks (Tasks 4, 6)
frontend/src/lib/irBlocks/toIr.ts            blocksToIr (Tasks 4, 6)
frontend/src/lib/irBlocks/*.test.ts
frontend/src/components/BlocksEditor.tsx     the editable workspace over the draft (Task 5, 8)
frontend/src/components/modelStyles/BlocklyView.tsx   read-only view on the new vocabulary; Edit mode (Tasks 5, 9)
frontend/src/lib/modelBlocks.ts              removed in Task 5 (replaced by irBlocks); partOfBlock moves to irBlocks/catalogue.ts
backend/app/api/problems.py                  POST /problems/{id}/versions/validate (Task 7)
backend/tests/template_irs.json              every template's IR, for the frontend round trip (Task 4)
backend/tests/test_template_irs.py           the file cannot drift from the templates (Task 4)
```

Queue mapping: **Blocks 1** = Tasks 1–2 · **Blocks 2** = Tasks 3–5 · **Blocks 3** = Task 6 · **Blocks 4** = Tasks 7–9. After each queue item: full check (`bash scripts/check.sh`), commit by path, deploy from a clean worktree, `docker image prune -f`, browser check with screenshots, tick the queue item and update the handover.

---

### Task 1: The shared draft store

**Files:**
- Create: `frontend/src/model/draftStore.ts`, `frontend/src/model/draftStore.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type DraftBase = "scratch" | `version-${number}`;
  export type ModelDraft = { problemId: number; base: DraftBase; baseVersion: number | null; ir: Record<string, unknown>; editedAt: string; persisted: boolean };
  export const DRAFT_KEY_PREFIX = "solver_model_draft_";
  export function readDraft(problemId: number): ModelDraft | null;
  export function writeDraft(draft: { problemId: number; base: DraftBase; baseVersion: number | null; ir: Record<string, unknown> }): ModelDraft;
  export function updateDraftIr(problemId: number, update: (ir: Record<string, unknown>) => Record<string, unknown>): ModelDraft | null;
  export function clearDraft(problemId: number): void;
  export function useModelDraft(problemId: number): ModelDraft | null;
  ```
  `persisted` is false when storage threw (Review Focus 4).

- [ ] **Step 1: Failing tests**

```ts
// frontend/src/model/draftStore.test.ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DRAFT_KEY_PREFIX, clearDraft, readDraft, updateDraftIr, useModelDraft, writeDraft } from "./draftStore";

const IR = { version: 2, sets: ["day"], parameters: {}, variables: {}, constraints: [] };

afterEach(() => {
  localStorage.clear();
  clearDraft(1);
  clearDraft(2);
  vi.restoreAllMocks();
});

describe("the draft store", () => {
  it("keeps one draft per problem, with what it was seeded from and when it was edited", () => {
    const saved = writeDraft({ problemId: 1, base: "version-7", baseVersion: 3, ir: IR });
    expect(readDraft(1)).toEqual(saved);
    expect(saved.persisted).toBe(true);
    expect(Number.isNaN(Date.parse(saved.editedAt))).toBe(false);
    expect(readDraft(2)).toBeNull();
    expect(JSON.parse(localStorage.getItem(`${DRAFT_KEY_PREFIX}1`)!).ir).toEqual(IR);
  });

  it("updates from the store's current value, never from a caller's stale copy", () => {
    writeDraft({ problemId: 1, base: "version-7", baseVersion: 3, ir: IR });
    // Another tab wrote a newer draft behind this page's back.
    localStorage.setItem(`${DRAFT_KEY_PREFIX}1`, JSON.stringify({ ...readDraft(1), ir: { ...IR, sets: ["day", "shift"] } }));
    window.dispatchEvent(new StorageEvent("storage", { key: `${DRAFT_KEY_PREFIX}1` }));
    const next = updateDraftIr(1, (ir) => ({ ...ir, variables: { x: { index: [], domain: "binary" } } }));
    expect(next!.ir.sets).toEqual(["day", "shift"]);
    expect(next!.ir.variables).toEqual({ x: { index: [], domain: "binary" } });
  });

  it("tells subscribers, and follows another tab", () => {
    const { result } = renderHook(() => useModelDraft(1));
    expect(result.current).toBeNull();
    act(() => void writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: IR }));
    expect(result.current?.base).toBe("scratch");
    act(() => {
      localStorage.setItem(`${DRAFT_KEY_PREFIX}1`, JSON.stringify({ ...result.current, base: "version-9" }));
      window.dispatchEvent(new StorageEvent("storage", { key: `${DRAFT_KEY_PREFIX}1` }));
    });
    expect(result.current?.base).toBe("version-9");
    act(() => clearDraft(1));
    expect(result.current).toBeNull();
  });

  it("keeps a stable snapshot between renders (useSyncExternalStore would loop otherwise)", () => {
    writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: IR });
    const { result, rerender } = renderHook(() => useModelDraft(1));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("keeps editing in memory when storage throws, and says it is not persisted", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    const saved = writeDraft({ problemId: 2, base: "scratch", baseVersion: null, ir: IR });
    expect(saved.persisted).toBe(false);
    expect(readDraft(2)?.ir).toEqual(IR);
  });

  it("ignores a stored value that is not a draft", () => {
    localStorage.setItem(`${DRAFT_KEY_PREFIX}1`, "{not json");
    expect(readDraft(1)).toBeNull();
    localStorage.setItem(`${DRAFT_KEY_PREFIX}1`, JSON.stringify({ problemId: 1, ir: "nope" }));
    expect(readDraft(1)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to see them fail** — `npx vitest run src/model/draftStore.test.ts` → FAIL, module not found.

- [ ] **Step 3: Implement**

```ts
// frontend/src/model/draftStore.ts
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
  let draft: ModelDraft | null = null;
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
```

- [ ] **Step 4: Run** — `npx vitest run src/model/draftStore.test.ts` → 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/model/draftStore.ts frontend/src/model/draftStore.test.ts
git commit -m "feat(model): one shared unpublished draft per problem, in this browser (Blocks 1)"
```

---

### Task 2: The Model editor on the draft store

**Files:**
- Create: `frontend/src/model/draftIr.ts`, `frontend/src/model/draftIr.test.ts`, `frontend/src/model/DraftBar.tsx`
- Modify: `frontend/src/pages/ModelEditor.tsx` (the `Editor` component: `useState<Draft>` → the store), `frontend/src/pages/ModelEditor.test.tsx`

**Interfaces:**
- Consumes: Task 1's store.
- Produces:
  ```ts
  // draftIr.ts
  export type FormDraft = { sets: string[]; parameters: Record<string, ParameterSpec>; variables: Record<string, VariableSpec>; constraints: Constraint[]; objective: { sense: string; mode: string; terms: ObjectiveTerm[] } };
  export function formDraftOf(ir: Record<string, unknown>): FormDraft;           // the seeding code moved out of ModelEditor
  export function withFormDraft(ir: Record<string, unknown>, draft: FormDraft): Record<string, unknown>; // every other key of `ir` kept
  export function publishable(ir: Record<string, unknown>): Record<string, unknown>; // today's `nextIr` body: version bump, derived relationships, cleaning
  // DraftBar.tsx
  export default function DraftBar(props: { draft: ModelDraft | null; publishing: boolean; blocked: string | null; onPublish(): void; onDiscard(): void }): JSX.Element | null;
  export function DraftConflict(props: { draft: ModelDraft; shownVersion: number | null; onContinue(): void; onStartAgain(): void }): JSX.Element;
  ```

- [ ] **Step 1: Move the projection out, with tests.** `formDraftOf` is exactly the object `ModelEditor` builds in its seeding effect today (lines ~225–240: sets copied, parameters/variables shallow-copied, constraints mapped `{...c}`, objective sense default `"minimize"`, mode `"lex"` else `"weighted"`, terms copied). `withFormDraft(ir, d)` returns `{...ir, sets: d.sets, parameters: d.parameters, variables: d.variables, constraints: d.constraints, objective: {...(ir.objective ?? {}), sense: d.objective.sense, mode: d.objective.mode, terms: d.objective.terms}}`. `publishable(ir)` is today's `nextIr` memo body verbatim (it already takes `ir` and the draft; call it with `withFormDraft`'s result and read the draft through `formDraftOf`).

```ts
// frontend/src/model/draftIr.test.ts
import { describe, expect, it } from "vitest";
import { formDraftOf, publishable, withFormDraft } from "./draftIr";

const IR = {
  version: 1, sets: ["cell", "zone"], relationships: ["adjacent"], parameters: {},
  variables: { assign: { index: ["cell", "zone"], domain: "binary" } },
  constraints: [{ id: "c", note: "  ", connected: { assign: { var: "assign", index: ["u", "z"] }, units: { index: "u", set: "cell" }, groups: { index: "z", set: "zone" }, via: "adjacent" }, severity: "hard", weight: 3 }],
};

describe("the form projection of a draft", () => {
  it("keeps every key the forms do not show, relationships included", () => {
    const draft = formDraftOf(IR);
    const back = withFormDraft({ ...IR, extra: { kept: true } }, { ...draft, sets: ["cell", "zone", "day"] });
    expect(back.relationships).toEqual(["adjacent"]);
    expect(back.extra).toEqual({ kept: true });
    expect(back.sets).toEqual(["cell", "zone", "day"]);
  });

  it("publishes what the forms always published: current version, walked relationships, no blank note, no hard weight", () => {
    const out = publishable(IR);
    expect(out.version).toBe(2);
    expect(out.relationships).toEqual(["adjacent"]);
    expect((out.constraints as Record<string, unknown>[])[0]).not.toHaveProperty("note");
    expect((out.constraints as Record<string, unknown>[])[0]).not.toHaveProperty("weight");
  });
});
```

Run `npx vitest run src/model/draftIr.test.ts` → FAIL (module missing); create `draftIr.ts` by moving the code; run → PASS.

- [ ] **Step 2: Failing page tests** (append to `frontend/src/pages/ModelEditor.test.tsx`; its `stub()` serves version 22 = `IR_V2`):

```tsx
describe("ModelEditor and the shared draft", () => {
  beforeEach(() => localStorage.clear());

  it("keeps an edit across a reload, with the badge", async () => {
    const first = renderPage();
    const note = await screen.findByDisplayValue("each day is staffed");
    fireEvent.change(note, { target: { value: "each day has enough people" } });
    expect(screen.getByText(/^Unpublished changes · edited \d{2}:\d{2}$/)).toBeInTheDocument();
    first.unmount();
    renderPage();
    expect(await screen.findByDisplayValue("each day has enough people")).toBeInTheDocument();
  });

  it("never swaps a draft from another version silently", async () => {
    localStorage.setItem("solver_model_draft_1", JSON.stringify({
      problemId: 1, base: "version-21", baseVersion: 1, editedAt: "2026-09-24T12:00:00Z", persisted: true,
      ir: { ...IR_V2, constraints: [] },
    }));
    renderPage();
    expect(await screen.findByText(/unpublished changes started from version 1/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start again from version 2/i }));
    expect(await screen.findByDisplayValue("c_cover")).toBeInTheDocument();
    expect(localStorage.getItem("solver_model_draft_1")).toBeNull();
  });

  it("clears the draft on publish, and on a confirmed discard only", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("each day is staffed"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(localStorage.getItem("solver_model_draft_1")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    await waitFor(() => expect(localStorage.getItem("solver_model_draft_1")).toBeNull());
  });

  it("says when changes cannot outlive the page", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("each day is staffed"), { target: { value: "y" } });
    expect(screen.getByText(/not saved in this browser: they are lost on reload/i)).toBeInTheDocument();
  });
});
```

Run `npx vitest run src/pages/ModelEditor.test.tsx` → the four new tests FAIL.

- [ ] **Step 3: Move the `Editor` onto the store.**
  - Replace `const [draft, setDraft] = useState<Draft | null>(null)` and the seeding effect with:
    ```tsx
    const stored = useModelDraft(Number(problemId));
    const conflict = stored !== null && seedKey !== null && stored.base !== seedKey && !(scratch && stored.base === "scratch");
    const workingIr = !conflict && stored ? stored.ir : ir;          // no draft yet: the version itself
    const draft = workingIr ? formDraftOf(workingIr) : null;
    function setDraft(update: (current: FormDraft) => FormDraft) {
      if (!workingIr || seedKey === null) return;
      if (readDraft(Number(problemId))) {
        updateDraftIr(Number(problemId), (current) => withFormDraft(current, update(formDraftOf(current))));
      } else {
        writeDraft({ problemId: Number(problemId), base: seedKey as DraftBase, baseVersion: base?.version ?? null,
                     ir: withFormDraft(workingIr, update(formDraftOf(workingIr))) });
      }
    }
    ```
    Every existing `setDraft((current) => current && {...})` call keeps its shape; drop the `current &&` guard (the store always has a current value when `setDraft` runs).
  - A draft exists only once something is edited: opening the page writes nothing (so visiting does not raise the badge).
  - `nextIr` becomes `workingIr ? publishable(withFormDraft(workingIr, draft!)) : null`.
  - When `conflict`: render only `<DraftConflict>` in place of the editor. **Continue** → `setSearchParams` to the draft's base (`version` param, or `setScratch(true)` for `"scratch"`); **Start again** → `clearDraft(problemId)`.
  - "Start a model" → `setScratch(true)` and `writeDraft({problemId, base: "scratch", baseVersion: null, ir: {...EMPTY_MODEL}})`.
  - Publish `onSuccess` → `clearDraft(problemId)` before moving the URL.
  - Render `<DraftBar>` above the Publish button row; its Publish button replaces today's (same label "Publish a new version", same disabled rule), plus **Discard** → inline "Discard the unpublished changes? [Discard them] [Keep editing]".
  - Badge: `Unpublished changes · edited ${HH:MM}` (local time, `toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", hour12: false})`); when `!draft.persisted`, add "— not saved in this browser: they are lost on reload".

- [ ] **Step 4: Run** — `npx vitest run src/pages/ModelEditor.test.tsx src/model` → all PASS (the existing 41 editor tests unchanged).

- [ ] **Step 5: Full check, commit, deploy (frontend only), browser check** (edit a rule's note, reload, badge and text survive; Discard asks; Publish clears), screenshots, tick **Blocks 1**.

```bash
git add frontend/src/model/draftIr.ts frontend/src/model/draftIr.test.ts frontend/src/model/DraftBar.tsx frontend/src/pages/ModelEditor.tsx frontend/src/pages/ModelEditor.test.tsx
git commit -m "feat(model): the Model editor edits the shared draft -- kept across reloads, never swapped silently (Blocks 1)"
```

---

### Task 3: The block vocabulary for declarations, plain rules and goal terms

**Files:**
- Create: `frontend/src/lib/irBlocks/catalogue.ts`, `frontend/src/lib/irBlocks/vocabulary.ts`, `frontend/src/lib/irBlocks/vocabulary.test.ts`

**Interfaces:**
- Produces:
  ```ts
  // catalogue.ts
  export type BlockCatalogue = {
    entityTypes: { name: string; attributes: { name: string; data_type: string }[] }[];
    parameters: { name: string; index: string[] }[];          // the domain's parameter defs, index as set names
    relationships: { name: string; from: string; to: string }[];
  };
  export const EMPTY_CATALOGUE: BlockCatalogue;
  export function setCatalogue(workspace: Blockly.Workspace, catalogue: BlockCatalogue): void;
  export function catalogueOf(workspace: Blockly.Workspace | null | undefined): BlockCatalogue;
  /** index name -> set name, for every index bound around `block` (rule forall, enclosing sums' over, earlier bindings in the same stack). */
  export function scopeAt(block: Blockly.Block): Map<string, string>;
  /** Declared decisions and data, read live from the model root's DECLARE stack. */
  export function declared(workspace: Blockly.Workspace): { variables: Map<string, { index: string[]; domain: string }>; parameters: Map<string, { index: string[] }>; sets: string[] };
  export function partOfBlock(id: string | null, parentOf: (id: string) => string | null, known: Set<string>): string | null; // moved from modelBlocks.ts
  export const NONE = "";
  // vocabulary.ts
  export const IR_BLOCK_TYPES: readonly string[];
  export function defineIrBlocks(): void;   // idempotent
  ```
- Block types (this task): `ir_model`, `ir_set`, `ir_variable`, `ir_parameter`, `ir_rule`, `ir_binding`, `ir_filter`, `ir_goal_term`, `ir_const`, `ir_var`, `ir_par`, `ir_attr`, `ir_sum`, `ir_add`, `ir_mul`, and three opaque carriers `ir_opaque_declaration`, `ir_opaque_rule`, `ir_opaque_term` (Task 4 uses them for constructs Task 6 has not built yet).
- Field names (Tasks 4 and 6 rely on these exactly):

| block | fields | inputs | extraState |
|---|---|---|---|
| `ir_model` | `TITLE` (label), `SENSE` (`minimize`/`maximize`), `MODE` (`weighted`/`lex`) | statements `DECLARE` (check `declaration`), `RULES` (`rule`), `GOAL` (`goal_term`) | `{version: number}` |
| `ir_set` | `SET` | — | — |
| `ir_variable` | `NAME`, `ARITY` (`0`..`4`), `SET0..SET3`, `DOMAIN` (`binary`/`integer`/`continuous`), `LOWER`, `UPPER` (text, number or empty) | — | `{arity}` |
| `ir_parameter` | `NAME` (dropdown), `INDEX` (label, `[a, b]`) | — | `{index: string[]}` |
| `ir_rule` | `ID`, `NOTE`, `SEVERITY` (`hard`/`soft`), `WEIGHT` (text), `RELATION` (`<=`/`=`/`>=`) | statement `FORALL` (`binding`); values `LEFT`, `RIGHT` (`Number`) | — |
| `ir_binding` | `INDEX`, `SET`, `VIA_REL` (`""` or a relationship), `VIA_END` (`from`/`to`), `VIA_ANCHOR`, `VIA_DEPTH` (`""`/`one`/`any`/`any_or_self`) | statement `WHERE` (`filter`) | — |
| `ir_filter` | `ATTR`, `OP` (the eight `FILTER_OPERATORS`), `VALUE` (JSON literal text) | — | — |
| `ir_goal_term` | `ID`, `WEIGHT` (text) | value `EXPRESSION` | — |
| `ir_const` | `VALUE` (text; empty = unfinished) | — | — |
| `ir_var` / `ir_par` | `NAME`, `IDX0..IDX3` | — | `{arity}` |
| `ir_attr` | `OF`, `NAME` | — | — |
| `ir_sum` | — | statement `OVER` (`binding`); value `BODY` | — |
| `ir_add` | `COUNT` (`2`..`8`) | values `T0..T7` | `{count}` |
| `ir_mul` | — | values `A`, `B` | — |
| `ir_opaque_*` | `LABEL` (label) | — | `{json: unknown}` |

- [ ] **Step 1: Failing tests** (headless workspace; no browser)

```ts
// frontend/src/lib/irBlocks/vocabulary.test.ts
import * as Blockly from "blockly";
import { beforeAll, describe, expect, it } from "vitest";
import { EMPTY_CATALOGUE, scopeAt, setCatalogue } from "./catalogue";
import { defineIrBlocks } from "./vocabulary";

const CATALOGUE = {
  entityTypes: [
    { name: "employee", attributes: [{ name: "hours", data_type: "integer" }, { name: "name", data_type: "text" }] },
    { name: "day", attributes: [] },
  ],
  parameters: [{ name: "demand", index: ["day"] }],
  relationships: [{ name: "works_with", from: "employee", to: "employee" }],
};

function options(block: Blockly.Block, field: string): string[] {
  return (block.getField(field) as Blockly.FieldDropdown).getOptions(false).map(([, value]) => value as string);
}

function load(blocks: object[]): Blockly.Workspace {
  const ws = new Blockly.Workspace();
  setCatalogue(ws, CATALOGUE);
  Blockly.serialization.workspaces.load({ blocks: { languageVersion: 0, blocks } }, ws);
  return ws;
}

const MODEL = (rules: object, declare?: object) => ({
  type: "ir_model", id: "root", extraState: { version: 2 },
  inputs: { ...(declare ? { DECLARE: { block: declare } } : {}), RULES: { block: rules } },
});

beforeAll(() => defineIrBlocks());

describe("what a block offers", () => {
  it("offers a data block only the indices bound to the set its parameter expects", () => {
    const par = { type: "ir_par", id: "p", extraState: { arity: 1 }, fields: { NAME: "demand", IDX0: "d" } };
    const ws = load([MODEL(
      { type: "ir_rule", id: "r", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
        inputs: {
          FORALL: { block: { type: "ir_binding", fields: { INDEX: "e", SET: "employee" },
            next: { block: { type: "ir_binding", fields: { INDEX: "d", SET: "day" } } } } },
          LEFT: { block: par } } },
      { type: "ir_parameter", fields: { NAME: "demand" }, extraState: { index: ["day"] } },
    )]);
    const block = ws.getBlockById("p")!;
    expect([...scopeAt(block)]).toEqual([["e", "employee"], ["d", "day"]]);
    expect(options(block, "IDX0")).toEqual(["d"]);
  });

  it("offers inside a sum's body the sum's own indices too, and not outside it", () => {
    const ws = load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_sum", id: "s",
        inputs: { OVER: { block: { type: "ir_binding", fields: { INDEX: "e", SET: "employee" } } },
                  BODY: { block: { type: "ir_attr", id: "a", fields: { OF: "e", NAME: "hours" } } } } } },
        RIGHT: { block: { type: "ir_attr", id: "b", fields: { OF: "", NAME: "" } } } } })]);
    expect(options(ws.getBlockById("a")!, "OF")).toEqual(["e"]);
    expect(options(ws.getBlockById("a")!, "NAME")).toEqual(["hours"]); // a number: text attributes are not offered
    expect(options(ws.getBlockById("b")!, "OF")).toEqual([""]);
  });

  it("keeps a value that is no longer offered, rather than blanking it (Review Focus 2, 5)", () => {
    const ws = load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "gone" } } } } },
      { type: "ir_set", id: "set", fields: { SET: "renamed_type" } })]);
    expect(ws.getBlockById("v")!.getFieldValue("NAME")).toBe("gone");
    expect(ws.getBlockById("set")!.getFieldValue("SET")).toBe("renamed_type");
    expect(options(ws.getBlockById("set")!, "SET")).toContain("renamed_type");
  });

  it("reshapes a decision's index slots with its arity, and saves the shape", () => {
    const ws = load([{ type: "ir_variable", id: "x", extraState: { arity: 1 }, fields: { NAME: "x", SET0: "day", DOMAIN: "binary" } }]);
    const block = ws.getBlockById("x")!;
    block.setFieldValue("2", "ARITY");
    block.setFieldValue("employee", "SET1");
    const saved = Blockly.serialization.blocks.save(block) as { extraState: unknown; fields: Record<string, string> };
    expect(saved.extraState).toEqual({ arity: 2 });
    expect([saved.fields.SET0, saved.fields.SET1]).toEqual(["day", "employee"]);
  });

  it("shows a rule's weight only when the rule is soft", () => {
    const ws = load([{ type: "ir_rule", id: "r", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" } }]);
    const rule = ws.getBlockById("r")!;
    expect(rule.getField("WEIGHT")!.isVisible()).toBe(false);
    rule.setFieldValue("soft", "SEVERITY");
    expect(rule.getField("WEIGHT")!.isVisible()).toBe(true);
  });

  it("refuses a name the platform would refuse, and a name already declared", () => {
    const ws = load([
      { type: "ir_variable", id: "a", extraState: { arity: 0 }, fields: { NAME: "x", DOMAIN: "binary" } },
      { type: "ir_variable", id: "b", extraState: { arity: 0 }, fields: { NAME: "y", DOMAIN: "binary" } },
    ]);
    const b = ws.getBlockById("b")!;
    b.setFieldValue("Bad Name", "NAME");
    expect(b.getFieldValue("NAME")).toBe("y");
    b.setFieldValue("x", "NAME");
    expect(b.getFieldValue("NAME")).toBe("y");
  });

  it("loads an unchosen dropdown as NONE and saves it back", () => {
    const ws = load([{ type: "ir_set", id: "s", fields: { SET: "" } }]);
    setCatalogue(ws, EMPTY_CATALOGUE);
    expect((Blockly.serialization.blocks.save(ws.getBlockById("s")!) as { fields: { SET: string } }).fields.SET).toBe("");
  });
});
```

- [ ] **Step 2: Run** `npx vitest run src/lib/irBlocks` → FAIL (modules missing).

- [ ] **Step 3: Implement `catalogue.ts`.**

```ts
// frontend/src/lib/irBlocks/catalogue.ts
/**
 * What an editable block may offer. A dropdown is only ever filled from
 * here and from the block's own surroundings, so it offers admissible
 * choices -- the rule the forms' `ReferencePicker` applies -- and always
 * keeps the value it already holds, even one the domain no longer has, so a
 * loaded model shows what it says and round-trips exactly.
 */
import type * as Blockly from "blockly";

export const NONE = "";

export type BlockCatalogue = {
  entityTypes: { name: string; attributes: { name: string; data_type: string }[] }[];
  parameters: { name: string; index: string[] }[];
  relationships: { name: string; from: string; to: string }[];
};
export const EMPTY_CATALOGUE: BlockCatalogue = { entityTypes: [], parameters: [], relationships: [] };

const catalogues = new WeakMap<Blockly.Workspace, BlockCatalogue>();
export function setCatalogue(workspace: Blockly.Workspace, catalogue: BlockCatalogue): void {
  catalogues.set(workspace, catalogue);
}
export function catalogueOf(workspace: Blockly.Workspace | null | undefined): BlockCatalogue {
  return (workspace && catalogues.get(workspace)) || EMPTY_CATALOGUE;
}

/** Blockly options for `values`, keeping `current` first-class even when it is no longer offered. */
export function menu(values: string[], current: string | null | undefined, label: (value: string) => string = (v) => v || "(choose)"): [string, string][] {
  const all = [...values];
  if (current !== null && current !== undefined && !all.includes(current)) all.unshift(current);
  if (all.length === 0) all.push(NONE);
  return all.map((value) => [label(value), value]);
}

function bindingsOf(first: Blockly.Block | null): [string, string][] {
  const out: [string, string][] = [];
  for (let b = first; b; b = b.getNextBlock()) {
    if (b.type === "ir_binding") out.push([b.getFieldValue("INDEX"), b.getFieldValue("SET")]);
  }
  return out;
}

/** The statement input of `parent` that `child` sits in (directly or down its stack). */
function inputHolding(parent: Blockly.Block, child: Blockly.Block): string | null {
  for (const input of parent.inputList) {
    let b = input.connection?.targetBlock() ?? null;
    while (b) {
      if (b === child) return input.name;
      b = b.getNextBlock();
    }
  }
  return null;
}

/**
 * index -> set for every index bound around `block`: the enclosing rule's
 * FORALL (and a scheduling rule's OVER, Task 6), enclosing sums' OVER when
 * the block is in the sum's BODY, and -- for a binding -- the bindings
 * before it in its own stack (a `via` anchors on an earlier index, never on
 * itself). Outer scopes first, so a Map keeps the reading order.
 */
export function scopeAt(block: Blockly.Block): Map<string, string> {
  const layers: [string, string][][] = [];
  if (block.type === "ir_binding") {
    // The bindings above this one in its own stack. `getPreviousBlock()` of
    // the first binding is the block that holds the stack (a rule, a sum),
    // which is not a binding, so the walk stops there.
    const before: [string, string][] = [];
    let came: Blockly.Block = block;
    for (let b = block.getPreviousBlock(); b && b.type === "ir_binding" && b.getNextBlock() === came; came = b, b = b.getPreviousBlock()) {
      before.unshift([b.getFieldValue("INDEX"), b.getFieldValue("SET")]);
    }
    layers.push(before);
  }
  let child: Blockly.Block = block;
  for (let parent = block.getSurroundParent(); parent; child = parent, parent = parent.getSurroundParent()) {
    const holding = inputHolding(parent, child) ?? parent.getInputWithBlock(child)?.name ?? null;
    if (parent.type === "ir_sum" && holding === "BODY") layers.unshift(bindingsOf(parent.getInputTargetBlock("OVER")));
    if (parent.type === "ir_sum" && holding === "OVER") continue;
    if (["ir_rule", "ir_no_overlap", "ir_cumulative"].includes(parent.type) && holding !== "FORALL") {
      if (["ir_no_overlap", "ir_cumulative"].includes(parent.type) && holding !== "OVER") layers.unshift(bindingsOf(parent.getInputTargetBlock("OVER")));
      layers.unshift(bindingsOf(parent.getInputTargetBlock("FORALL")));
    }
  }
  const scope = new Map<string, string>();
  for (const layer of layers) for (const [index, set] of layer) if (index && !scope.has(index)) scope.set(index, set);
  return scope;
}

export function declared(workspace: Blockly.Workspace) {
  const variables = new Map<string, { index: string[]; domain: string }>();
  const parameters = new Map<string, { index: string[] }>();
  const sets: string[] = [];
  const root = workspace.getBlockById("model-root");
  for (let b = root?.getInputTargetBlock("DECLARE") ?? null; b; b = b.getNextBlock()) {
    if (b.type === "ir_set") sets.push(b.getFieldValue("SET"));
    if (b.type === "ir_variable") {
      const arity = Number(b.getFieldValue("ARITY"));
      variables.set(b.getFieldValue("NAME"), {
        index: Array.from({ length: arity }, (_, i) => b.getFieldValue(`SET${i}`)),
        domain: b.getFieldValue("DOMAIN"),
      });
    }
    if (b.type === "ir_parameter") parameters.set(b.getFieldValue("NAME"), { index: (b as unknown as { index: string[] }).index ?? [] });
  }
  return { variables, parameters, sets };
}

export function partOfBlock(id: string | null, parentOf: (id: string) => string | null, known: Set<string>): string | null {
  let current = id;
  while (current) {
    if (known.has(current)) return current;
    current = parentOf(current);
  }
  return null;
}
```

- [ ] **Step 4: Implement `vocabulary.ts`.** Custom blocks through `Blockly.Blocks[type] = { init, saveExtraState, loadExtraState }`, colours from today's `modelBlocks.ts` `COLOUR` table (moved here). Shared helpers:

```ts
// frontend/src/lib/irBlocks/vocabulary.ts (the helpers and three representative blocks; every other block follows the same helpers and the table in this task's Interfaces)
import * as Blockly from "blockly";
import { FILTER_OPERATORS, RELATIONS, SEVERITIES, TRAVERSAL_DEPTHS } from "../../ir/contract";
import { NONE, catalogueOf, declared, menu, scopeAt } from "./catalogue";

const NAME = /^[a-z][a-z0-9_]*$/;
type B = Blockly.Block & Record<string, unknown>;

/** A dropdown whose options are recomputed each time it opens, from the block's surroundings. */
function dynamic(values: (block: Blockly.Block) => string[]): Blockly.FieldDropdown {
  const field: Blockly.FieldDropdown = new Blockly.FieldDropdown(function (this: Blockly.FieldDropdown) {
    const block = this.getSourceBlock();
    return menu(block ? values(block) : [], this.getValue());
  });
  return field;
}
const fixedMenu = (values: readonly string[]) => new Blockly.FieldDropdown(values.map((v) => [v, v]));

/** A name the platform accepts and no other declaration of this kind uses. */
function nameField(initial: string, kind: "ir_variable" | "ir_rule" | "ir_goal_term"): Blockly.FieldTextInput {
  return new Blockly.FieldTextInput(initial, function (this: Blockly.FieldTextInput, text: string) {
    if (!NAME.test(text)) return null;
    const block = this.getSourceBlock();
    const clash = block?.workspace.getAllBlocks(false).some(
      (other) => other !== block && other.type === kind && (other.getFieldValue("NAME") ?? other.getFieldValue("ID")) === text
    );
    return clash ? null : text;
  });
}

/** A number, or empty for "not given" (bounds, weights) -- never other text. */
const numberText = (initial: string) =>
  new Blockly.FieldTextInput(initial, (text: string) => (text === "" || Number.isFinite(Number(text)) ? text : null));

/** Index slots IDX0..: `arity` of them, each offering the indices bound here to the set the declaration expects there. */
function reshapeRefSlots(block: B, arity: number, expected: (i: number) => string | undefined) {
  const had = Number(block.arity ?? 0);
  for (let i = arity; i < had; i += 1) block.removeInput(`SLOT${i}`, true);
  for (let i = had; i < arity; i += 1) {
    block.appendDummyInput(`SLOT${i}`).appendField(i === 0 ? "[" : ",").appendField(
      dynamic((b) => [...scopeAt(b)].filter(([, set]) => set === expected(i)).map(([index]) => index)),
      `IDX${i}`
    );
  }
  block.arity = arity;
}

export function defineIrBlocks(): void {
  if (Blockly.Blocks.ir_model) return;

  Blockly.Blocks.ir_var = {
    init(this: B) {
      this.appendDummyInput("HEAD").appendField(
        new Blockly.FieldDropdown(function (this: Blockly.FieldDropdown) {
          const ws = this.getSourceBlock()?.workspace;
          const names = ws ? [...declared(ws).variables].filter(([, v]) => v.domain !== "interval").map(([n]) => n) : [];
          return menu(names, this.getValue());
        }, (name: string) => {
          const ws = this.workspace;
          reshapeRefSlots(this, declared(ws).variables.get(name)?.index.length ?? Number(this.arity ?? 0),
            (i) => declared(ws).variables.get(this.getFieldValue("NAME"))?.index[i]);
          return name;
        }),
        "NAME"
      );
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour("#3b82f6");
      this.arity = 0;
    },
    saveExtraState(this: B) { return { arity: this.arity }; },
    loadExtraState(this: B, state: { arity: number }) {
      reshapeRefSlots(this, state.arity, (i) => declared(this.workspace).variables.get(this.getFieldValue("NAME"))?.index[i]);
    },
  };

  Blockly.Blocks.ir_rule = {
    init(this: B) {
      this.appendDummyInput().appendField("rule").appendField(nameField("c_1", "ir_rule"), "ID")
        .appendField(fixedMenu(SEVERITIES).setValidator((severity: string) => {
          this.getField("WEIGHT")?.setVisible(severity === "soft");
          if (this.rendered) (this as unknown as Blockly.BlockSvg).queueRender();
          return severity;
        }), "SEVERITY")
        .appendField(numberText("1"), "WEIGHT");
      this.appendDummyInput().appendField("means").appendField(new Blockly.FieldTextInput(""), "NOTE");
      this.appendStatementInput("FORALL").setCheck("binding").appendField("for every");
      this.appendValueInput("LEFT").setCheck("Number");
      this.appendDummyInput().appendField(fixedMenu(RELATIONS), "RELATION");
      this.appendValueInput("RIGHT").setCheck("Number");
      this.setInputsInline(false);
      this.setPreviousStatement(true, "rule");
      this.setNextStatement(true, "rule");
      this.setColour("#334155");
      this.getField("WEIGHT")!.setVisible(false);
    },
  };

  Blockly.Blocks.ir_filter = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("where")
        .appendField(dynamic((b) => {
          const binding = b.getSurroundParent();
          const set = binding?.getFieldValue("SET");
          return (catalogueOf(b.workspace).entityTypes.find((t) => t.name === set)?.attributes ?? []).map((a) => a.name);
        }), "ATTR")
        .appendField(fixedMenu(FILTER_OPERATORS), "OP")
        .appendField(new Blockly.FieldTextInput('""', (text: string) => {
          try { JSON.parse(text); return text; } catch { return null; }
        }), "VALUE");
      this.setPreviousStatement(true, "filter");
      this.setNextStatement(true, "filter");
      this.setColour("#0f766e");
    },
  };

  // ir_model, ir_set, ir_variable, ir_parameter, ir_binding, ir_goal_term, ir_const, ir_par, ir_attr,
  // ir_sum, ir_add, ir_mul and the three ir_opaque_* blocks: the same helpers, the field and input
  // names in this task's table. Specifics:
  //  - ir_model: deletable false; SENSE and MODE fixed menus; extraState {version}.
  //  - ir_set: SET = dynamic(entity types not already declared by another ir_set).
  //  - ir_variable: ARITY fixed menu "0".."4" whose validator adds/removes SET0.. dropdowns of
  //    catalogue entity types (reshape as reshapeRefSlots does); DOMAIN fixed menu
  //    binary/integer/continuous (Task 6 adds interval); LOWER/UPPER numberText, hidden for binary.
  //  - ir_parameter: NAME = dynamic(catalogue parameter names); its validator sets `this.index`
  //    from the catalogue def and the INDEX label to `[day, shift]`; extraState {index}.
  //  - ir_par: as ir_var, over declared(ws).parameters.
  //  - ir_attr: OF = dynamic(indices in scopeAt); NAME = dynamic(attributes of scopeAt's set for OF
  //    whose data_type is integer or number).
  //  - ir_binding: INDEX text (NAME pattern); SET = dynamic(declared sets); VIA_REL =
  //    dynamic(["", ...relationships touching SET]); VIA_END fixed from/to; VIA_ANCHOR =
  //    dynamic(indices bound before it whose set is the other end of VIA_REL); VIA_DEPTH fixed
  //    ["", ...TRAVERSAL_DEPTHS]; WHERE statement (check "filter"); previous/next "binding".
  //  - ir_add: COUNT fixed "2".."8" whose validator adds/removes value inputs T0..; extraState {count}.
  //  - ir_opaque_*: LABEL label; extraState {json}; previous/next "declaration" | "rule" or output
  //    "Number"; setEditable(false) (it can be moved and deleted, not edited).
}

export const IR_BLOCK_TYPES = [
  "ir_model", "ir_set", "ir_variable", "ir_parameter", "ir_rule", "ir_binding", "ir_filter", "ir_goal_term",
  "ir_const", "ir_var", "ir_par", "ir_attr", "ir_sum", "ir_add", "ir_mul",
  "ir_opaque_declaration", "ir_opaque_rule", "ir_opaque_term",
] as const;
```

- [ ] **Step 5: Run** `npx vitest run src/lib/irBlocks` → 7 PASS. Fix the scope walk until the "earlier bindings" and "sum body only" cases hold; do not loosen the tests.

- [ ] **Step 6: Commit** `feat(blocks): an editable block vocabulary that only offers admissible choices (Blocks 2)`.

---

### Task 4: `irToBlocks`, `blocksToIr` and the exact round trip

**Files:**
- Create: `frontend/src/lib/irBlocks/toBlocks.ts`, `frontend/src/lib/irBlocks/toIr.ts`, `frontend/src/lib/irBlocks/roundTrip.test.ts`, `backend/tests/template_irs.json`, `backend/tests/test_template_irs.py`

**Interfaces:**
- Consumes: Task 3's block and field names.
- Produces:
  ```ts
  export type IrLoc = (string | number)[];
  export function irToBlocks(ir: Record<string, unknown>, options?: { editable?: boolean; title?: string; ids?: (loc: IrLoc) => string | undefined }): { blocks: { languageVersion: 0; blocks: SerialBlock[] } };
  export function blocksToIr(workspace: { blocks?: { blocks?: SerialBlock[] } }): { ir: Record<string, unknown>; paths: Map<string, IrLoc>; outside: number };
  ```
  `ids` lets the read-only view keep the model graph's node ids (`model-set-…`, `model-var-…`, `model-con-…`, `model-objective`) on the blocks that stand for model parts, so selection still opens the side panel. `outside` counts top-level blocks other than the root (Review Focus 1).

- [ ] **Step 1: The template fixture (backend).** `backend/tests/test_template_irs.py`:

```python
"""Every template's IR, as the frontend's Blocks round trip reads it (Blocks 2).

The frontend cannot import Python, so the templates are written to
tests/template_irs.json. This test fails when the file and the templates
disagree; `SOLVER_WRITE_TEMPLATE_IRS=1 pytest tests/test_template_irs.py`
rewrites it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.seed import WEEKLY_ROTA_TEMPLATE, weekly_rota_template_ir
from app.showcase import SHOWCASE

PATH = Path(__file__).parent / "template_irs.json"


def _templates() -> dict:
    return {WEEKLY_ROTA_TEMPLATE: weekly_rota_template_ir(), **{name: ir for name, (_seed, ir) in SHOWCASE.items()}}


def test_the_frontend_reads_every_template_as_it_is():
    wanted = json.dumps(_templates(), indent=1, sort_keys=True) + "\n"
    if os.environ.get("SOLVER_WRITE_TEMPLATE_IRS") == "1":
        PATH.write_text(wanted, encoding="utf-8")
    assert PATH.read_text(encoding="utf-8") == wanted, "run with SOLVER_WRITE_TEMPLATE_IRS=1 to refresh"
```

Run it once with `SOLVER_WRITE_TEMPLATE_IRS=1` (writes the file), then without (PASS).

- [ ] **Step 2: Failing round-trip test**

```ts
// frontend/src/lib/irBlocks/roundTrip.test.ts
import * as Blockly from "blockly";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { EMPTY_CATALOGUE, setCatalogue } from "./catalogue";
import { blocksToIr } from "./toIr";
import { irToBlocks } from "./toBlocks";
import { defineIrBlocks } from "./vocabulary";

function above(relative: string): string {
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} not found`);
  }
}
const FIXTURES = JSON.parse(readFileSync(above("backend/tests/ir_fixtures.json"), "utf8")) as { valid: { name: string; ir: Record<string, unknown> }[] };
const TEMPLATES = JSON.parse(readFileSync(above("backend/tests/template_irs.json"), "utf8")) as Record<string, Record<string, unknown>>;
const CASES: [string, Record<string, unknown>][] = [
  ...FIXTURES.valid.map((f) => [`fixture ${f.name}`, f.ir] as [string, Record<string, unknown>]),
  ...Object.entries(TEMPLATES).map(([name, ir]) => [`template ${name}`, ir] as [string, Record<string, unknown>]),
];

/** The only two differences the blocks may make, both without meaning. */
function canonical(ir: Record<string, unknown>): Record<string, unknown> {
  const out = JSON.parse(JSON.stringify(ir));
  if (Array.isArray(out.relationships)) out.relationships = [...out.relationships].sort();
  if (out.objective?.mode === "weighted") delete out.objective.mode;
  return out;
}

/** Through a real (headless) workspace, as the editor does -- not only data to data. */
function throughWorkspace(ir: Record<string, unknown>) {
  const ws = new Blockly.Workspace();
  setCatalogue(ws, EMPTY_CATALOGUE); // Review Focus 5: no option list holds any of these values
  Blockly.serialization.workspaces.load(irToBlocks(ir, { editable: true }), ws);
  const saved = Blockly.serialization.workspaces.save(ws);
  ws.dispose();
  return blocksToIr(saved as Parameters<typeof blocksToIr>[0]);
}

beforeAll(() => defineIrBlocks());

describe("blocks round-trip every model exactly", () => {
  it.each(CASES)("%s", (_name, ir) => {
    const { ir: back, outside } = throughWorkspace(ir);
    expect(outside).toBe(0);
    expect(canonical(back)).toEqual(canonical(ir));
  });

  it("covers every fixture and template (a new one is picked up, not skipped)", () => {
    expect(CASES.length).toBe(FIXTURES.valid.length + Object.keys(TEMPLATES).length);
    expect(CASES.length).toBeGreaterThanOrEqual(28);
  });
});

describe("blocksToIr", () => {
  it("keeps an unfinished block as a named refusal, not a silent change", () => {
    const { ir, paths } = blocksToIr({ blocks: { blocks: [{ type: "ir_model", id: "model-root", extraState: { version: 2 },
      inputs: { RULES: { block: { type: "ir_rule", id: "r", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" },
        inputs: { LEFT: { block: { type: "ir_const", id: "k", fields: { VALUE: "3" } } } } } } } }] } });
    expect((ir.constraints as Record<string, unknown>[])[0].right).toEqual({ const: null });
    expect(paths.get("k")).toEqual(["constraints", 0, "left"]);
    expect(paths.get("r")).toEqual(["constraints", 0]);
  });

  it("counts blocks left outside the model (Review Focus 1)", () => {
    const { outside } = blocksToIr({ blocks: { blocks: [
      { type: "ir_model", id: "model-root", extraState: { version: 2 } },
      { type: "ir_rule", id: "stray", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" } },
    ] } });
    expect(outside).toBe(1);
  });
});
```

Run `npx vitest run src/lib/irBlocks/roundTrip.test.ts` → FAIL (modules missing).

- [ ] **Step 3: `toBlocks.ts`.** One function per construct, each returning a `SerialBlock` and recursing; statement lists linked with the `stack()` helper moved from `modelBlocks.ts`; every block `id` from `options.ids?.(loc)` or generated as `b${counter}`; `editable: false` adds `{movable: false, deletable: false, editable: false}` to every block (today's read-only look). Construct → block, exactly:
  - root: `ir_model`, `id: "model-root"`, `x: 24, y: 24`, `extraState: {version: ir.version}`, fields `TITLE`, `SENSE: objective?.sense ?? "minimize"`, `MODE: objective?.mode ?? "weighted"`; `DECLARE` = sets, then variables, then parameters (IR key order preserved within each); `RULES` = constraints in order; `GOAL` = objective terms in order.
  - `ir_set`: `{SET: name}`. `ir_variable`: `extraState {arity: index.length}`, `NAME`, `ARITY: String(arity)`, `SET{i}`, `DOMAIN`, `LOWER`/`UPPER` = `String(value)` or `""`. A variable with `domain: "interval"`, or any key beyond `index/domain/lower/upper` → `ir_opaque_declaration` with `extraState {json: {kind: "variable", name, spec}}` (Task 6 replaces).
  - `ir_parameter`: `NAME`, `INDEX` label, `extraState {index}`; a parameter with `uncertainty` → `ir_opaque_declaration` `{kind: "parameter", name, spec}` (Task 6).
  - A constraint with `left`/`relation`/`right` and no `when`: `ir_rule` with `ID`, `NOTE: note ?? ""`, `SEVERITY`, `WEIGHT: String(weight ?? 1)`, `RELATION`, `FORALL` stack, `LEFT`, `RIGHT`. Anything else (`when`, `no_overlap`, `cumulative`, `connected`) → `ir_opaque_rule` `{json: constraint}` (Task 6).
  - binding: `ir_binding` `INDEX`, `SET`, `VIA_REL: via?.rel ?? ""`, `VIA_END: via?.to !== undefined ? "to" : "from"`, `VIA_ANCHOR: via?.from ?? via?.to ?? ""`, `VIA_DEPTH: via?.depth ?? ""`, `WHERE` stack of `ir_filter {ATTR, OP, VALUE: JSON.stringify(value)}`.
  - terms: `const` → `ir_const {VALUE: String(const)}`; `var`/`par` → `ir_var`/`ir_par` `{NAME, IDX{i}}` `extraState {arity}`; `attr` → `ir_attr {OF, NAME}`; `sum` → `ir_sum` `OVER` stack + `BODY`; `add` → `ir_add` `extraState {count: n}`, `COUNT`, `T{i}`; `mul` → `ir_mul` `A`, `B`; `pwl`, `fn` → `ir_opaque_term {json: term}` (Task 6).
  - goal term: `ir_goal_term {ID, WEIGHT: String(weight)}`, `EXPRESSION`.
  - An `add` with more than 8 parts: `ir_add` of 8 whose last input is the `add` of the rest — **not** equivalent after a round trip (it would nest). So `toBlocks` uses `ir_opaque_term` for an `add` of more than 8 parts, and Task 6 raises `COUNT` to 16 and keeps the opaque fallback beyond it; the round-trip test covers the fixture `wideAdd` only through its generated form, which is an invalid fixture, so no valid case exceeds 8.

- [ ] **Step 4: `toIr.ts`.** The exact inverse, walking the serialised JSON (no Blockly runtime), recording `paths.set(block.id, loc)` for every block it reads, where `loc` is the IR location the block produced:
  - `ir_model` (the top-level block with `id === "model-root"`; `outside` = number of other top-level blocks): `version` from `extraState.version`; `sets`/`variables`/`parameters` from `DECLARE` in stack order (a variable is `{index, domain}` plus `lower`/`upper` when the text is non-empty, as numbers); `constraints` from `RULES`; `objective` only when `GOAL` holds at least one term: `{sense, ...(MODE === "lex" ? {mode: "lex"} : {}), terms}`; `relationships` = sorted union of every `VIA_REL` and every opaque rule's `connected.via` and every opaque term's walked rels, present only when non-empty.
  - `ir_rule` → `{id, ...(NOTE ? {note} : {}), ...(FORALL ? {forall} : {}), left, relation, right, severity, ...(severity === "soft" ? {weight: Number(WEIGHT)} : {})}`. **Key order matters nowhere** (the test compares values), but the IR's own key names are exact.
  - An empty `LEFT`/`RIGHT`/`BODY`/`A`/`B`/`T{i}`/`EXPRESSION` → `{const: null}`; `ir_const` with `VALUE === ""` → `{const: null}`; otherwise `Number(VALUE)`.
  - `ir_binding` → `{index, set, ...(WHERE ? {where: [{attr, op, value: JSON.parse(VALUE)}]} : {}), ...(VIA_REL ? {via: {rel, [VIA_END]: VIA_ANCHOR, ...(VIA_DEPTH ? {depth} : {})}} : {})}`.
  - `ir_opaque_*` → `extraState.json` itself (a declaration's `{kind, name, spec}` is put back under `variables[name]` / `parameters[name]`).

- [ ] **Step 5: Run** `npx vitest run src/lib/irBlocks` → all PASS. A failing fixture names the construct `toBlocks`/`toIr` lose; fix the conversion, not the fixture.

- [ ] **Step 6: Commit** `feat(blocks): irToBlocks and blocksToIr, exact over every fixture and template (Blocks 2)`.

---

### Task 5: The Blocks editor, the Model editor's Blocks tab, and the read-only view on the new vocabulary

**Files:**
- Create: `frontend/src/components/BlocksEditor.tsx`, `frontend/src/components/BlocksEditor.test.tsx`
- Modify: `frontend/src/pages/ModelEditor.tsx` (tabs), `frontend/src/components/modelStyles/BlocklyView.tsx`, `frontend/src/components/modelStyles/types.ts` (catalogue prop), `frontend/src/lib/modelBlocks.test.ts` (rewritten against `irBlocks`)
- Delete: `frontend/src/lib/modelBlocks.ts`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces: `<BlocksEditor ir catalogue onChange(ir, paths, outside) refusalAt?: {blockId, message} />`; `export function catalogueFrom(entityTypes, parameterDefs, relationshipTypes): BlockCatalogue` (in `catalogue.ts`).

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/BlocksEditor.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BlocksEditor from "./BlocksEditor";

const IR = { version: 2, sets: ["day"], parameters: {}, variables: { x: { index: ["day"], domain: "binary" } }, constraints: [] };

describe("BlocksEditor", () => {
  it("shows the draft as blocks and reports each change as IR", async () => {
    const onChange = vi.fn();
    render(<BlocksEditor ir={IR} catalogue={{ entityTypes: [{ name: "day", attributes: [] }], parameters: [], relationships: [] }} onChange={onChange} />);
    const host = await screen.findByTestId("blocks-editor");
    expect(host.querySelector(".blocklySvg")).not.toBeNull();
    // A programmatic edit through the workspace the component exposes for tests.
    const ws = (host as unknown as { __workspace: import("blockly").Workspace }).__workspace;
    ws.getBlockById("model-root")!.setFieldValue("maximize", "SENSE");
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [ir, , outside] = onChange.mock.calls.at(-1)!;
    expect(ir.variables).toEqual(IR.variables);
    expect(outside).toBe(0);
  });

  it("does not reload over the person's own edit when the draft echoes it back", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<BlocksEditor ir={IR} catalogue={{ entityTypes: [], parameters: [], relationships: [] }} onChange={onChange} />);
    const ws = ((await screen.findByTestId("blocks-editor")) as unknown as { __workspace: import("blockly").Workspace }).__workspace;
    const root = ws.getBlockById("model-root")!;
    root.setFieldValue("maximize", "SENSE");
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    rerender(<BlocksEditor ir={onChange.mock.calls.at(-1)![0]} catalogue={{ entityTypes: [], parameters: [], relationships: [] }} onChange={onChange} />);
    expect(ws.getBlockById("model-root")).toBe(root); // same block object: not reloaded
  });
});
```

(Blockly's `inject` needs an SVG-capable DOM; if jsdom lacks what `inject` needs, keep these two tests on a headless `Blockly.Workspace` behind the same `onChange` wiring — extract `bindWorkspace(ws, onChange)` and test that — and let the live browser check cover `inject`.)

Update the Model editor test: "switching Forms → Blocks → Forms keeps an edit made in the forms" (`fireEvent.click(tab "Blocks")`, then back, the edited note is still shown), and "the Blocks tab says the forms are the accessible path".

- [ ] **Step 2: Implement `BlocksEditor`.** Inject with `renderer: "zelos"`, the toolbox (categories *Declare*, *Rules*, *Goal*, *Values*, *Arithmetic*; a category's block omitted when the catalogue has nothing to fill it: no `ir_par` without a parameter, no `ir_set` without an entity type), `trashcan: true`, `sounds: false`, `move` and `zoom` as `BlocklyView` today. `setCatalogue(workspace, catalogue)` before loading `irToBlocks(ir, {editable: true})`. A change listener: ignore UI events (`event.isUiEvent`), coalesce to one `requestAnimationFrame`, then `blocksToIr(Blockly.serialization.workspaces.save(workspace))` → `onChange(ir, paths, outside)`; remember `lastEmitted = JSON.stringify(ir)`. On a new `ir` prop: reload only when `JSON.stringify(ir) !== lastEmitted` (Discard, a Forms-tab edit, another tab). Re-lay out (`workspace.cleanUp()`) only after a reload. Expose `workspace` on the host element as `__workspace` for tests.

- [ ] **Step 3: Model editor tabs.** Above the declarations: a tablist **Forms | Blocks** (`role="tablist"`, `aria-selected`), default Forms, remembered in the URL (`?view=blocks`). Blocks tab renders `<BlocksEditor ir={workingIr} catalogue={catalogueFrom(entityTypes, parameters, relationshipTypes)} onChange={(ir) => writeOrUpdateDraft(ir)} />` (the same write path `setDraft` uses, with the whole IR) and, beside the tablist: "Blocks are a drag-and-drop view of the same model. The forms are the keyboard and screen-reader way to edit it."

- [ ] **Step 4: `BlocklyView` on the new vocabulary.** `defineIrBlocks()` instead of `defineBlocksWithJsonArray(BLOCK_DEFINITIONS)`; load `irToBlocks(ir, {editable: false, title, ids: (loc) => nodeIdFor(loc)})` where `nodeIdFor` maps `["sets", i]` → `model-set-<name>` (or the entity type's node id, as today), `["variables", name]` → `model-var-<name>`, `["parameters", name]` → `model-par-<name>`, `["constraints", i]` → `model-con-<id>`, `["objective"]` → `model-objective`; `partOfBlock` from `irBlocks/catalogue`. Rewrite `modelBlocks.test.ts` as `irBlocks/readOnly.test.ts`: every block is fixed; the part blocks carry those node ids; a scheduling and a connected rule are drawn (as opaque blocks until Task 6) and not as "(no expression)". Delete `modelBlocks.ts`.

- [ ] **Step 5: Run** `npx vitest run src/components src/lib src/pages/ModelEditor.test.tsx src/model` → PASS. Full check; commit; deploy the frontend; browser check: open the Model editor, Blocks tab, change the sense dropdown and a rule's relation by mouse, see the badge, switch to Forms and see the same change, publish; screenshots; tick **Blocks 2**.

```bash
git add frontend/src/components/BlocksEditor.tsx frontend/src/components/BlocksEditor.test.tsx frontend/src/pages/ModelEditor.tsx frontend/src/pages/ModelEditor.test.tsx frontend/src/components/modelStyles/BlocklyView.tsx frontend/src/components/modelStyles/types.ts frontend/src/lib/irBlocks frontend/src/lib/modelBlocks.ts frontend/src/lib/modelBlocks.test.ts
git commit -m "feat(blocks): the Model editor's Blocks tab over the shared draft; the optimization view draws the same blocks (Blocks 2)"
```

---

### Task 6: The advanced constructs' blocks

**Files:**
- Modify: `frontend/src/lib/irBlocks/vocabulary.ts`, `toBlocks.ts`, `toIr.ts`, `roundTrip.test.ts`, `vocabulary.test.ts`

**Interfaces:**
- Produces these block types and fields (`toBlocks`/`toIr` convert exactly as Task 4 does for the basic ones):

| block | fields | inputs | extraState |
|---|---|---|---|
| `ir_variable` (extended) | `DOMAIN` gains `interval`; for it `START`, `END` (dropdowns of integer decisions), `SIZE` (text: a whole number, or a parameter name offered as a dropdown value), `PRESENCE` (`""` or a binary decision) | — | `{arity}` |
| `ir_parameter` (extended) | `UNCERTAINTY` (`exact`/`interval`/`scenarios`), `DEVIATION` (text, a fraction, shown for interval), `GAMMA` (text, empty or a number, shown for interval) | — | `{index}` |
| `ir_rule` (extended) | — | statement `WHEN` (check `when`, at most one block) | — |
| `ir_when` | `VAR` (binary decisions), `IDX0..3`, `IS` (`yes`/`no`) | — | `{arity, isGiven: boolean}` |
| `ir_no_overlap` | `ID`, `NOTE`, `INTERVAL` (interval decisions), `IDX0..3` | statements `FORALL`, `OVER` | `{arity}` |
| `ir_cumulative` | as `ir_no_overlap` | + values `DEMAND`, `CAPACITY` | `{arity}` |
| `ir_connected` | `ID`, `NOTE`, `VAR` (from `connectedChoices` in `model/terms.ts`), `VIA`, `U_INDEX`, `Z_INDEX` (text), `EMPTY` (checkbox) | — | `{emptyGiven: boolean}` |
| `ir_pwl` | `VAR` (numeric decisions), `IDX0..3`, `COUNT` (`2`..`12`), `X0..`, `Y0..` (number text) | — | `{arity, count}` |
| `ir_fn` | `NAME` (the `FUNCTIONS` catalogue, labelled `log — concave`) | value `OF` | — |
| `ir_add` (extended) | `COUNT` up to `16` | `T0..T15` | `{count}` |

`isGiven` / `emptyGiven` record whether the loaded IR wrote the key (`is: 1` and `empty: "forbidden"` are the defaults; writing them back only when they were there keeps the round trip exact). `scopeAt` already treats `ir_no_overlap`/`ir_cumulative` like a rule (Task 3), with `OVER` adding to the scope of `INTERVAL`'s slots and `DEMAND`.

- [ ] **Step 1: Failing tests.** In `roundTrip.test.ts` add:

```ts
it("needs no opaque block for any fixture or template: every construct has its own block", () => {
  for (const [name, ir] of CASES) {
    const types = JSON.stringify(irToBlocks(ir, { editable: true }));
    expect(types, name).not.toMatch(/"type":"ir_opaque_/);
  }
});
```

and in `vocabulary.test.ts`: an `ir_when` inside a rule offers only binary decisions and indices bound by the rule; an `ir_connected` offers only `connectedChoices`' variables and their self-relationships; an `ir_fn` lists every `FUNCTIONS` name with its curvature; an `ir_cumulative`'s `DEMAND` sees the `OVER` index, its `CAPACITY` does not.

- [ ] **Step 2: Run** → the opaque test FAILS naming the first fixture with a `when`, `pwl`, `fn`, interval, scheduling, `connected` or uncertainty.

- [ ] **Step 3: Implement** each block with Task 3's helpers; `toBlocks` stops emitting `ir_opaque_*` for these constructs (keep the opaque blocks defined: a future construct lands there first, visibly, instead of breaking the editor); `toIr` inverts each.

- [ ] **Step 4: Run** `npx vitest run src/lib/irBlocks` → PASS, including every fixture and template with no opaque block.

- [ ] **Step 5: Full check, commit, deploy, browser check** (open the workshop template in the Blocks tab: `no_overlap` and intervals are editable blocks; change a duration size, publish, solve, makespan 9), tick **Blocks 3**.

```bash
git add frontend/src/lib/irBlocks
git commit -m "feat(blocks): every construct as its own block -- conditions, curves, functions, intervals, scheduling, connected, uncertainty, lex goals (Blocks 3)"
```

---

### Task 7: The dry-run validate route

**Files:**
- Modify: `backend/app/api/problems.py`, `frontend/src/api/v1.ts`
- Test: `backend/tests/test_validate_version.py`

**Interfaces:**
- Produces: `POST /api/v1/problems/{problem_id}/versions/validate` with body `{"ir": {...}}` → `200 {"ok": true}` or the same `422` body publish returns (`field_error(["ir", *loc], message, …)`), writing nothing; requires `model.publish` like publish. Frontend `validateVersion(problemId, ir)` and `useValidateVersion(problemId, ir)` — a TanStack query keyed by `JSON.stringify(ir)`, `enabled` only when `checkIrShape(ir) === null`, the key debounced 500 ms (`useDebouncedValue`).

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_validate_version.py
"""Checking a draft against the domain without publishing it (Blocks 4)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_tenancy import IR, tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_problem  # noqa: F401


def test_a_valid_draft_is_ok_and_nothing_is_written(tenants, db):  # noqa: F811
    problem = make_problem(db, tenants["domain_a"])
    before = db.execute(text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": problem}).scalar_one()
    answer = TestClient(app).post(f"/api/v1/problems/{problem}/versions/validate", json={"ir": IR}, headers=tenants["a"])
    assert answer.status_code == 200 and answer.json() == {"ok": True}
    after = db.execute(text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": problem}).scalar_one()
    assert after == before


def test_a_refused_draft_answers_as_publish_would(tenants, db):  # noqa: F811
    problem = make_problem(db, tenants["domain_a"])
    bad = {**IR, "sets": ["no_such_type"]}
    client = TestClient(app)
    checked = client.post(f"/api/v1/problems/{problem}/versions/validate", json={"ir": bad}, headers=tenants["a"])
    published = client.post(f"/api/v1/problems/{problem}/versions", json={"ir": bad}, headers=tenants["a"])
    assert checked.status_code == published.status_code == 422
    assert checked.json() == published.json()


def test_another_organization_cannot_validate_against_this_problem(tenants, db):  # noqa: F811
    problem = make_problem(db, tenants["domain_a"])
    answer = TestClient(app).post(f"/api/v1/problems/{problem}/versions/validate", json={"ir": IR}, headers=tenants["b"])
    assert answer.status_code == 404
```

- [ ] **Step 2: Implement** in `app/api/problems.py`, beside `create_version`:

```python
@router.post("/problems/{problem_id}/versions/validate")
def validate_version(
    problem_id: int,
    payload: ModelVersionCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("model.publish")),
) -> dict[str, bool]:
    """What publishing this IR would say, without publishing it: the
    Blocks editor asks on every pause, so a refusal the domain alone can
    make (a set that is not an entity type) shows before Publish."""
    _check_ir(db, _get_problem(db, problem_id), payload.ir)
    return {"ok": True}
```

(Declare it **before** any `/problems/{problem_id}/versions/{…}` route that could capture `validate`.)

- [ ] **Step 3: Frontend client** in `v1.ts`: `export const validateVersion = (problemId: Id, ir: Record<string, unknown>) => send<{ ok: true }>("POST", \`/api/v1/problems/${problemId}/versions/validate\`, { ir });` and the hook; the Model editor shows the server's refusal (parsed with `formatApiError`) under the Publish button and disables Publish while it stands.

- [ ] **Step 4: Run** the backend test → PASS; `npx vitest run src/pages/ModelEditor.test.tsx` (add: a domain refusal from the validate route disables Publish and is shown) → PASS. Commit `feat(api): validate a draft against the domain without publishing it (Blocks 4)`.

---

### Task 8: Refusals on the blocks

**Files:**
- Modify: `frontend/src/components/BlocksEditor.tsx`, `frontend/src/model/DraftBar.tsx`, `frontend/src/pages/ModelEditor.tsx`
- Test: `frontend/src/components/BlocksEditor.test.tsx`, `frontend/src/lib/irBlocks/refusals.test.ts`

**Interfaces:**
- Produces: `export function blockForLoc(paths: Map<string, IrLoc>, loc: IrLoc): string | null` (in `toIr.ts`) — the block whose recorded path is the longest prefix of `loc`; `BlocksEditor` prop `refusal?: { loc: IrLoc; message: string } | null` puts `setWarningText(message)` on that block (clearing the previous one) and scrolls it into view when `reveal` changes.

- [ ] **Step 1: Failing tests**

```ts
// frontend/src/lib/irBlocks/refusals.test.ts
import { describe, expect, it } from "vitest";
import { checkIrShape } from "../../ir/validate";
import { blockForLoc, blocksToIr } from "./toIr";

const WS = { blocks: { blocks: [{ type: "ir_model", id: "model-root", extraState: { version: 2 },
  inputs: {
    DECLARE: { block: { type: "ir_variable", id: "x", extraState: { arity: 0 }, fields: { NAME: "x", ARITY: "0", DOMAIN: "binary", LOWER: "", UPPER: "" } } },
    RULES: { block: { type: "ir_rule", id: "r", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_mul", id: "m", inputs: { A: { block: { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "x" } } } } } },
                RIGHT: { block: { type: "ir_const", id: "k", fields: { VALUE: "1" } } } } } } } }] } };

describe("a refusal lands on the block that caused it", () => {
  it("an empty socket: the product whose second factor is missing", () => {
    const { ir, paths } = blocksToIr(WS);
    const refusal = checkIrShape({ ...ir, sets: [], parameters: {} })!;
    expect(refusal.code).toBe("const_not_a_number");
    expect(blockForLoc(paths, refusal.loc)).toBe("m");
  });

  it("a stale reference: the decision block that names a deleted decision (Review Focus 2)", () => {
    const stale = JSON.parse(JSON.stringify(WS));
    stale.blocks.blocks[0].inputs.DECLARE.block.fields.NAME = "y";
    stale.blocks.blocks[0].inputs.RULES.block.inputs.LEFT.block = { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "x" } };
    const { ir, paths } = blocksToIr(stale);
    const refusal = checkIrShape({ ...ir, sets: [], parameters: {} })!;
    expect(refusal.code).toBe("reference_undeclared");
    expect(blockForLoc(paths, refusal.loc)).toBe("v");
  });
});
```

In `BlocksEditor.test.tsx`: with `refusal={{loc: ["constraints", 0, "left"], message: "…"}}` the block at that path carries the warning text; a new refusal moves it; `null` clears it. In the Model editor test: with a rule dragged outside the root (`outside: 1` from `onChange`), Publish is disabled and the bar says "1 block is outside the model: put it inside, or delete it".

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** `blockForLoc` (walk `paths`, pick the entry whose value is the longest prefix of `loc`), the warning in `BlocksEditor` (`(ws.getBlockById(id) as Blockly.BlockSvg).setWarningText(message)`; clear the previous id with `setWarningText(null)`), and the DraftBar's first-refusal line + the outside-blocks refusal (Publish disabled while `outside > 0`). **Step 4: Run** → PASS. Commit `feat(blocks): a refusal is shown on the block that caused it (Blocks 4)`.

---

### Task 9: Edit mode in the optimization view, and the live check

**Files:**
- Modify: `frontend/src/components/GraphEditor.tsx` (style bar: an **Edit** toggle when the Blockly style is on and the person can `model.publish`), `frontend/src/components/modelStyles/BlocklyView.tsx` (`editing` prop: `BlocksEditor` over the draft with the DraftBar), `frontend/src/components/modelStyles/types.ts` (`problemId`, `versionId`, `canEdit`)
- Test: `frontend/src/components/modelStyles/BlocklyView.test.tsx`; live: `frontend/_browser_check_blocks.mjs` (gitignored)

**Interfaces:**
- Consumes: everything above. The optimization view's draft is the same `useModelDraft(problemId)`; a conflict shows `DraftConflict` as the Model editor does; Publish moves the view to the new version (`onModelTargetChange({problemId, versionId: created.id})`).

- [ ] **Step 1: Failing tests** — Edit off: read-only blocks, no toolbox; Edit on: toolbox present, the DraftBar present, an edit writes the draft, and the Model editor (rendered in the same test with the same problem) shows the edit — one shared draft; Selecting a block still calls `onSelect` with the model part's node id.

- [ ] **Step 2: Implement** the toggle (`aria-pressed`, label "Edit", title "Edit this model as blocks; the Model editor's forms are the keyboard-accessible way") and the editing branch.

- [ ] **Step 3: The feed-blend build, block by block, headless** (`frontend/src/lib/irBlocks/buildByBlocks.test.ts`): from an empty `ir_model` in a headless workspace with the feed-blend template's catalogue, create and connect each block through the API a person's drags perform (`ws.newBlock(type)`, `setFieldValue`, `connection.connect`) — set `feed`, decision `amount[feed]` continuous 0..100, data `cost[feed]`, rule `c_total: sum over f in feed of amount[f] = 100`, the protein and fibre rules with `ir_attr`, goal `1 × sum over f in feed of cost[f] × amount[f]` — then `blocksToIr(save(ws)).ir` must equal the feed-blend template's IR up to the two canonicalisations. This is the spec's "builds the feed-blend model from an empty draft by blocks alone", run where it can be exact; the live check below drives the same editor by mouse.

- [ ] **Step 4: The live browser check** (`_browser_check_blocks.mjs`): a fresh domain with `feed` (attributes `protein`, `fibre`), the parameter `cost`, a problem with no version; open the optimization view, Blockly style, **Edit**; from the toolbox **drag by mouse** a set block and a decision block into the model root, choose `feed` and type `amount`, set it continuous with bounds; drag a rule, a number block into each side; see the refusal badge while a socket is empty and the warning on that block; fill it; publish; then open the Blocks tab in the Model editor on the new version and see the same blocks; solve a published feed-blend built from the template to 43.5317 through the Blocks tab's Publish (template applied, one weight changed by blocks, published, solved, objective as expected). Screenshots of the toolbox, a refusal on a block, and the published model. Clean up the domain.

- [ ] **Step 5: Full check, commit, deploy, prune, tick Blocks 4**, update the handover (the Blockly edit mode is live; the spatial plan and the Blockly plan are both complete).

```bash
git add frontend/src/components/GraphEditor.tsx frontend/src/components/modelStyles frontend/src/lib/irBlocks/buildByBlocks.test.ts
git commit -m "feat(blocks): Edit mode in the optimization view over the shared draft (Blocks 4)"
```

---

## Self-review

- **Spec coverage.** §1 decisions → Tasks 3–6 (everything editable, advanced constructs), 2/5/9 (both places, one draft), 4 (approach A, no saved positions). §2 → Tasks 1–2 (store, seeding, Continue/Start again, badge, publish/discard), 7 (debounced domain check). §3 → Tasks 3 and 6 (every block, index slots from ancestors, categorised toolbox that offers only what can be filled: Task 5 Step 2). §4 → Task 4 (`blocksToIr`, sentinel for incomplete blocks, exact round trip over fixtures and templates) and Task 6 (no opaque block left). §5 → Task 8 (paths from `blocksToIr` rather than ids preserved across rebuilds — the same mapping with one moving part fewer). §6 → Tasks 5 (Blocks tab, layout, accessibility sentence), 7 (validate route), 9 (Edit toggle, undo/redo is Blockly's own). §7 → the tests named in each task; the feed-blend build is headless-exact (Task 9 Step 3) plus a live mouse-driven check (Step 4) — a deliberate split, since dragging every block of feed-blend by mouse in Playwright would make the check brittle rather than stronger.
- **Deviations from the spec, stated:** `blocksToIr` returns the path map instead of relying on preserved block ids (§5); the feed-blend build is proven headless, with a smaller mouse-driven live check (§7); Blocks 2 ships with opaque carriers for not-yet-built constructs so the round trip is exact from the first release, and Blocks 3's test is that none remain.
- **Types across tasks:** `ModelDraft`/`DraftBase` (Task 1) used in 2, 5, 9; `FormDraft`/`formDraftOf`/`withFormDraft`/`publishable` (2) used in 5; `BlockCatalogue`/`setCatalogue`/`scopeAt`/`declared`/`menu`/`NONE`/`partOfBlock` (3) used in 4–9; `irToBlocks`/`blocksToIr`/`IrLoc` (4) used in 5, 8, 9; `blockForLoc` (8); `validateVersion` (7). Field and input names are fixed in Task 3's and Task 6's tables.
- **Review Focus** tests are placed: 1 → Tasks 4 and 8; 2 → Tasks 3 and 8; 3 → Task 1; 4 → Tasks 1 and 2; 5 → Tasks 3 and 4.
