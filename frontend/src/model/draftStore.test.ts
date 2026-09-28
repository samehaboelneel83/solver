import { setToken } from "../api/client";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { draftStorageKey, draftHistory, replayDraft, clearDraft, readDraft, updateDraftIr, useModelDraft, writeDraft } from "./draftStore";

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
    expect(JSON.parse(localStorage.getItem(draftStorageKey(1))!).ir).toEqual(IR);
  });

  it("updates from the store's current value, never from a caller's stale copy", () => {
    writeDraft({ problemId: 1, base: "version-7", baseVersion: 3, ir: IR });
    // Another tab wrote a newer draft behind this page's back.
    localStorage.setItem(draftStorageKey(1), JSON.stringify({ ...readDraft(1), ir: { ...IR, sets: ["day", "shift"] } }));
    window.dispatchEvent(new StorageEvent("storage", { key: draftStorageKey(1) }));
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
      localStorage.setItem(draftStorageKey(1), JSON.stringify({ ...result.current, base: "version-9" }));
      window.dispatchEvent(new StorageEvent("storage", { key: draftStorageKey(1) }));
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
    localStorage.setItem(draftStorageKey(1), "{not json");
    expect(readDraft(1)).toBeNull();
    localStorage.setItem(draftStorageKey(1), JSON.stringify({ problemId: 1, ir: "nope" }));
    expect(readDraft(1)).toBeNull();
  });
});


it("undoes and redoes edits including the first edit, preserving unknown fields", () => {
  const initial = { ...IR, extension: { keep: true } };
  writeDraft({ problemId: 1, base: "version-7", baseVersion: 3, ir: { ...initial, sets: ["shift"] } }, initial);
  expect(replayDraft(1, "undo")).toBe(true);
  expect(readDraft(1)?.ir).toEqual(initial);
  expect(replayDraft(1, "redo")).toBe(true);
  expect(readDraft(1)?.ir.sets).toEqual(["shift"]);
  replayDraft(1, "undo");
  updateDraftIr(1, ir => ({ ...ir, sets: ["employee"] }));
  expect(draftHistory(1).canRedo).toBe(false);
});

it("refuses undo over a newer draft from another tab", () => {
  writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: IR });
  updateDraftIr(1, ir => ({ ...ir, sets: ["shift"] }));
  localStorage.setItem(draftStorageKey(1), JSON.stringify({ ...readDraft(1), ir: { ...IR, sets: ["external"] } }));
  expect(replayDraft(1, "undo")).toBe(false);
  expect(readDraft(1)?.ir.sets).toEqual(["external"]);
});

it("keeps the latest edit in memory if storage fills after an earlier save", () => {
  writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: IR });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
  updateDraftIr(1, ir => ({ ...ir, sets: ["latest"] }));
  expect(readDraft(1)?.ir.sets).toEqual(["latest"]);
  expect(readDraft(1)?.persisted).toBe(false);
  expect(replayDraft(1, "undo")).toBe(true);
  expect(readDraft(1)?.ir).toEqual(IR);
});


const tokenFor = (sub: string) => `header.${btoa(JSON.stringify({ sub }))}.signature`;

it("isolates persisted drafts and undo history by account", () => {
  setToken(tokenFor("alice"));
  writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: { ...IR, sets: ["alice"] } }, IR);
  const aliceKey = draftStorageKey(1);
  setToken(tokenFor("bob"));
  expect(readDraft(1)).toBeNull();
  expect(draftHistory(1).canUndo).toBe(false);
  writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: { ...IR, sets: ["bob"] } });
  expect(draftStorageKey(1)).not.toBe(aliceKey);
  setToken(tokenFor("alice"));
  expect(readDraft(1)?.ir.sets).toEqual(["alice"]);
  expect(replayDraft(1, "undo")).toBe(true);
  setToken(tokenFor("bob"));
  expect(readDraft(1)?.ir.sets).toEqual(["bob"]);
});

it("does not assign legacy drafts to the next signed-in user", () => {
  localStorage.setItem("solver_model_draft_1", JSON.stringify({ problemId: 1, base: "scratch", ir: IR, editedAt: new Date().toISOString() }));
  setToken(tokenFor("alice"));
  expect(readDraft(1)).toBeNull();
  expect(localStorage.getItem("solver_model_draft_1")).not.toBeNull();
});

it("isolates memory-only drafts when accounts change", () => {
  setToken(tokenFor("alice"));
  const fail = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
  writeDraft({ problemId: 2, base: "scratch", baseVersion: null, ir: IR });
  expect(readDraft(2)?.persisted).toBe(false);
  fail.mockRestore();
  setToken(tokenFor("bob"));
  expect(readDraft(2)).toBeNull();
  setToken(tokenFor("alice"));
  expect(readDraft(2)?.ir).toEqual(IR);
  clearDraft(2);
});
