import { describe, expect, it } from "vitest";
import { unitNotes, unitOf } from "./ModelReview";
import type { FormDraft } from "./draftIr";

const units = { drive: "min", length: "km", cost: "EGP" };

function draft(constraints: unknown[], terms: unknown[] = []): FormDraft {
  return { sets: [], parameters: {}, variables: {}, constraints, objective: { sense: "minimize", terms } } as unknown as FormDraft;
}

describe("units on data (improvement plan 5.4)", () => {
  it("reads a term's unit from its data", () => {
    expect(unitOf({ mul: [{ par: "drive" }, { var: "x" }] }, units)).toBe("min");
    expect(unitOf({ sum: { mul: [{ par: "cost" }, { var: "x" }] } }, units)).toBe("egp");
    expect(unitOf({ var: "x" }, units)).toBeNull();
  });

  it("flags minutes added to kilometres, and a comparison across units", () => {
    const notes = unitNotes(draft([
      { id: "c_mix", left: { add: [{ par: "drive" }, { par: "length" }] }, relation: "<=", right: { const: 5 } },
      { id: "c_cmp", left: { par: "drive" }, relation: "<=", right: { par: "cost" } },
      { id: "c_ok", left: { mul: [{ par: "drive" }, { var: "x" }] }, relation: "<=", right: { par: "drive" } },
    ]), units);
    expect(notes).toEqual([
      "c_mix adds min to km: check the units, or convert one first.",
      "c_cmp compares min with egp: check the units.",
    ]);
  });
});
