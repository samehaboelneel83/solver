import { setToken } from "../api/client";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { claimLegacyDraft, draftStorageKey, draftHistory, legacyDraftStatus, replayDraft, clearDraft, readDraft, updateDraftIr, useModelDraft, writeDraft } from "./draftStore";

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

const legacy = (ir = IR) => localStorage.setItem("solver_model_draft_1", JSON.stringify({ problemId: 1, base: "version-7", baseVersion: 3, ir, editedAt: "2026-09-01T10:00:00.000Z" }));

it("recovers a legacy draft only on an explicit claim, keeping the original", () => {
  legacy({ ...IR, sets: ["legacy"] });
  setToken(tokenFor("alice"));
  expect(legacyDraftStatus(1)).toBe("available");
  expect(readDraft(1)).toBeNull();
  const saved = claimLegacyDraft(1);
  expect(saved).toMatchObject({ problemId: 1, base: "version-7", baseVersion: 3, persisted: true });
  expect(readDraft(1)?.ir.sets).toEqual(["legacy"]);
  expect(legacyDraftStatus(1)).toBe("claimed-by-you");
  expect(JSON.parse(localStorage.getItem("solver_model_draft_1")!).ir.sets).toEqual(["legacy"]);
  expect(() => claimLegacyDraft(1)).toThrow(/already recovered/);
});

it("lets only one account claim a legacy draft", () => {
  legacy();
  setToken(tokenFor("alice"));
  claimLegacyDraft(1);
  setToken(tokenFor("bob"));
  expect(legacyDraftStatus(1)).toBe("claimed-by-other");
  expect(() => claimLegacyDraft(1)).toThrow(/another account/i);
  expect(readDraft(1)).toBeNull();
});

it("refuses to recover over the account's own draft, or without a named account", () => {
  legacy();
  expect(legacyDraftStatus(1)).toBe("signed-out");
  expect(() => claimLegacyDraft(1)).toThrow(/sign in/i);
  setToken("not-a-jwt");
  expect(legacyDraftStatus(1)).toBe("signed-out");
  setToken(tokenFor("alice"));
  writeDraft({ problemId: 1, base: "scratch", baseVersion: null, ir: { ...IR, sets: ["mine"] } });
  expect(() => claimLegacyDraft(1)).toThrow(/current unpublished draft/);
  expect(readDraft(1)?.ir.sets).toEqual(["mine"]);
  expect(legacyDraftStatus(1)).toBe("available");
});

it("does not claim unreadable legacy drafts, or keep a claim storage refused", () => {
  localStorage.setItem("solver_model_draft_1", "{not json");
  setToken(tokenFor("alice"));
  expect(legacyDraftStatus(1)).toBe("unreadable");
  expect(() => claimLegacyDraft(1)).toThrow(/could not be read/);
  legacy();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
  expect(() => claimLegacyDraft(1)).toThrow(/refused/);
  vi.restoreAllMocks();
  expect(legacyDraftStatus(1)).toBe("available");
  expect(readDraft(1)).toBeNull();
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
