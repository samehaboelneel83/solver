import { describe, expect, it } from "vitest";
import { termBlock } from "./modelBlocks";
import type { Term } from "../model/terms";

describe("termBlock", () => {
  it("shows a piecewise curve as the variable it is a curve of, not an unknown", () => {
    const term = { pwl: { var: "units", index: ["p"] }, points: [[0, 0], [2, 10]] } as Term;
    expect(termBlock(term)).toMatchObject({ type: "ir_var", fields: { NAME: "curve(units)", INDEX: "[p]" } });
  });
});
