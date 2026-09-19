import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { STALE_RECORD_PHRASE, isStaleRecordError } from "../api/errors";
import { mergeReload, reloadedKeys } from "./staleRecord";

/**
 * Ruling 42's two shared pieces, tested where they live rather than only
 * through the three forms that use them: the merge decides what a reload
 * leaves in the controls, and the predicate decides which 409 a form is
 * looking at. Both are small and both are easy to get subtly wrong in a
 * way a page test would report as something else entirely.
 */

describe("mergeReload", () => {
  const seeded = { a: "one", b: "two", c: "three" };

  it("keeps a value the person changed, even when the server changed it too", () => {
    const merged = mergeReload(seeded, { ...seeded, a: "mine" }, { ...seeded, a: "theirs" });
    expect(merged.a).toBe("mine");
  });

  it("takes the server's value for a control the person left alone", () => {
    const merged = mergeReload(seeded, seeded, { ...seeded, b: "theirs" });
    expect(merged.b).toBe("theirs");
  });

  it("keeps a value the person typed even when it equals nothing the server has", () => {
    const merged = mergeReload(seeded, { ...seeded, c: "" }, { ...seeded, c: "three" });
    expect(merged.c).toBe("");
  });

  it("does not mistake a person who typed the server's new value for an untouched control", () => {
    // They are the same string either way, so the outcome is the same --
    // which is the point: the merge can never produce a value neither side
    // asked for.
    const merged = mergeReload(seeded, { ...seeded, a: "theirs" }, { ...seeded, a: "theirs" });
    expect(merged.a).toBe("theirs");
  });

  it("carries falsy values rather than falling through to the other side", () => {
    // `false`, `0` and `""` are values. A merge written with `||` would
    // silently replace every one of them.
    const base = { flag: true, count: 5, text: "x" };
    const merged = mergeReload(base, { flag: false, count: 0, text: "" }, base);
    expect(merged).toStrictEqual({ flag: false, count: 0, text: "" });
  });

  it("takes its key set from the server, so a deleted definition does not come back", () => {
    const merged = mergeReload(
      { kept: "a", gone: "b" },
      { kept: "a", gone: "edited" },
      { kept: "fresh" } as { kept: string; gone: string }
    );
    expect(merged).toStrictEqual({ kept: "fresh" });
  });

  it("returns a new object rather than mutating any of its three inputs", () => {
    const current = { ...seeded, a: "mine" };
    const fresh = { ...seeded, b: "theirs" };
    const merged = mergeReload(seeded, current, fresh);
    expect(merged).not.toBe(current);
    expect(merged).not.toBe(fresh);
    expect(seeded).toStrictEqual({ a: "one", b: "two", c: "three" });
  });
});

describe("reloadedKeys", () => {
  const seeded = { a: "one", b: "two" };

  it("names only what actually came from the server", () => {
    expect(reloadedKeys(seeded, seeded, { a: "one", b: "theirs" })).toEqual(["b"]);
  });

  it("does not name a key the person is holding their own value for", () => {
    expect(reloadedKeys(seeded, { a: "mine", b: "two" }, { a: "theirs", b: "two" })).toEqual([]);
  });

  it("does not name a key the server returned unchanged", () => {
    expect(reloadedKeys(seeded, seeded, seeded)).toEqual([]);
  });
});

describe("isStaleRecordError", () => {
  const conflict = (detail: string) => new ApiError(409, JSON.stringify({ detail }));

  it("recognises the server's stale-record refusal", () => {
    expect(
      isStaleRecordError(
        conflict(`This entity was ${STALE_RECORD_PHRASE} after this form loaded it. Reload it.`)
      )
    ).toBe(true);
  });

  it("does not claim the other 409 a save can get", () => {
    expect(isStaleRecordError(conflict("a entity row with the same type_id already exists"))).toBe(
      false
    );
  });

  it("is false for every other status, including one whose body says the same thing", () => {
    expect(isStaleRecordError(new ApiError(422, JSON.stringify({ detail: [] })))).toBe(false);
    expect(
      isStaleRecordError(new ApiError(400, JSON.stringify({ detail: STALE_RECORD_PHRASE })))
    ).toBe(false);
  });

  it("is false for a non-API error and for an unparseable body", () => {
    expect(isStaleRecordError(new Error(STALE_RECORD_PHRASE))).toBe(false);
    expect(isStaleRecordError(new ApiError(409, "not json"))).toBe(false);
    expect(isStaleRecordError(null)).toBe(false);
  });
});
