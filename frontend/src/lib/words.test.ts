import { describe, expect, it } from "vitest";
import { WORDS, word } from "./words";

describe("one vocabulary", () => {
  it("says the plain word in Simple and keeps the term in Expert", () => {
    expect(word("Domain", true)).toBe("Workspace");
    expect(word("Domain", false)).toBe("Domain");
    expect(word("Entity type", true)).toBe("Kind of record");
  });

  it("has a plain word for every term, different from the term", () => {
    for (const [expert, simple] of Object.values(WORDS)) expect(simple).not.toBe(expert);
  });
});
