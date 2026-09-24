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
