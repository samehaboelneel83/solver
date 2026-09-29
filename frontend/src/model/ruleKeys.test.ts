import { describe, expect, it } from "vitest";
import { stableKeys } from "./ruleKeys";

describe("stable rule identities", () => {
  const first = stableKeys([], [], ["cover", "hours", "rest"]);

  it("gives each rule its own key", () => {
    expect(new Set(first).size).toBe(3);
  });

  it("keeps every key through a rename", () => {
    expect(stableKeys(["cover", "hours", "rest"], first, ["cover", "hours_max", "rest"])).toEqual(first);
  });

  it("keeps the others' keys when one is deleted", () => {
    expect(stableKeys(["cover", "hours", "rest"], first, ["cover", "rest"])).toEqual([first[0], first[2]]);
  });

  it("gives only an added rule a new key", () => {
    const next = stableKeys(["cover", "hours", "rest"], first, ["cover", "hours", "rest", "night"]);
    expect(next.slice(0, 3)).toEqual(first);
    expect(first).not.toContain(next[3]);
  });
});
