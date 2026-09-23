import { describe, expect, it } from "vitest";
import { termBlock } from "./modelBlocks";
import type { Term } from "../model/terms";

describe("termBlock", () => {
  it("shows a piecewise curve as the variable it is a curve of, not an unknown", () => {
    const term = { pwl: { var: "units", index: ["p"] }, points: [[0, 0], [2, 10]] } as Term;
    expect(termBlock(term)).toMatchObject({ type: "ir_var", fields: { NAME: "curve(units)", INDEX: "[p]" } });
  });

  it("shows a function as its name of its argument's block", () => {
    const term = { fn: "log", of: { add: [{ const: 1 }, { var: "spend", index: [] }] } } as Term;
    expect(termBlock(term)).toMatchObject({
      type: "ir_fn",
      fields: { NAME: "log" },
      inputs: { ARG: { block: { type: "ir_add" } } },
    });
  });
});

describe("modelToBlocks and a scheduling rule", () => {
  it("draws a no_overlap as its intervals that never overlap, not as an unexpressed rule", async () => {
    const { modelToBlocks } = await import("./modelBlocks");
    const ir = {
      sets: ["job"],
      parameters: {},
      variables: { task: { index: ["job"], domain: "interval" } },
      constraints: [
        { id: "c_room", no_overlap: { interval: { var: "task", index: ["j"] }, over: [{ index: "j", set: "job" }] }, severity: "hard" },
      ],
    };
    const json = JSON.stringify(modelToBlocks(ir, { nodes: [], edges: [], entity_types: [] } as never));
    expect(json).toContain("never overlap");
    expect(json).not.toContain("(no expression)");
    expect(json).toContain('"NAME":"task"');
  });
});

describe("modelToBlocks and a conditional rule", () => {
  it("reads the condition with what the rule holds for", async () => {
    const { modelToBlocks } = await import("./modelBlocks");
    const ir = {
      sets: [],
      parameters: {},
      variables: { open: { index: [], domain: "binary" }, ship: { index: [], domain: "integer" } },
      constraints: [
        { id: "c_closed", left: { var: "ship", index: [] }, relation: "<=", right: { const: 0 }, severity: "hard",
          when: { var: "open", index: [], is: 0 } },
      ],
    };
    const json = JSON.stringify(modelToBlocks(ir, { nodes: [], edges: [], entity_types: [] } as never));
    expect(json).toContain("nothing: it holds once, only while open[] is no");
  });
});
