import { describe, expect, it } from "vitest";
import { ruleSentence, termSentence } from "./ruleSentence";

describe("read-back that keeps its meaning (benchmark re-test, October 2026)", () => {
  it("keeps the brackets of a sum inside a product", () => {
    const term = { mul: [{ attr: { of: "r", name: "cost" } }, { add: [{ var: "x", index: ["r"] }, { var: "y", index: ["r"] }] }] } as never;
    expect(termSentence(term)).toBe("cost of r times (x of r plus y of r)");
  });

  it("reads another item of the set as itself, not as a field", () => {
    const rule = { id: "c_apart", left: { const: 0 }, relation: "<=", right: { const: 1 }, severity: "hard",
      forall: [{ index: "c", set: "site" }, { index: "c2", set: "site", where: [{ index: "c", op: ">" }, { attr: "open", op: "=", value: true }] }] } as never;
    expect(ruleSentence(rule)).toMatch(/^For every site c and every site c2 after c, whose open /);
  });
});
