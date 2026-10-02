import { describe, expect, it } from "vitest";
import { WORDS, word } from "./words";

describe("one vocabulary", () => {
  it("says Workspace and Data values at both levels; the record words still differ", () => {
    // Benchmark, October 2026: Expert renamed them Domain and Parameters, and testers lost their way.
    expect(word("Domain", true)).toBe("Workspace");
    expect(word("Domain", false)).toBe("Workspace");
    expect(word("Parameters", false)).toBe("Data values");
    expect(word("Entity type", true)).toBe("Kind of record");
    expect(word("Entity type", false)).toBe("Record type");
  });

  it("has a word at each level for every term", () => {
    for (const [expert, simple] of Object.values(WORDS)) expect(expert && simple).toBeTruthy();
  });
});
