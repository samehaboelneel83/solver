import { describe, expect, it } from "vitest";
import { irToBlocks, type SerialBlock } from "./toBlocks";
import { blocksToIr } from "./toIr";

/**
 * The constructs Blocks 3 gives their own blocks travel, until then, in an
 * opaque block that carries them verbatim: shown by name, not editable
 * here, and never lost or turned into "no expression".
 */
function* walk(block: SerialBlock): Generator<SerialBlock> {
  yield block;
  for (const input of Object.values(block.inputs ?? {})) yield* walk(input.block);
  if (block.next) yield* walk(block.next.block);
}

const X = { var: "x", index: [] };
const CASES: [string, Record<string, unknown>, string][] = [
  ["a piecewise curve", { id: "c", left: { pwl: { var: "units", index: ["p"] }, points: [[0, 0], [2, 10]] }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_opaque_term"],
  ["a function", { id: "c", left: { fn: "log", of: { add: [{ const: 1 }, X] } }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_opaque_term"],
  ["a scheduling rule", { id: "c_room", no_overlap: { interval: { var: "task", index: ["j"] }, over: [{ index: "j", set: "job" }] }, severity: "hard" }, "ir_opaque_rule"],
  ["a conditional rule", { id: "c_closed", left: X, relation: "<=", right: { const: 0 }, severity: "hard", when: { var: "open", index: [], is: 0 } }, "ir_opaque_rule"],
  ["a connected rule", { id: "c_zones", connected: { assign: { var: "assign", index: ["u", "z"] }, units: { index: "u", set: "cell" }, groups: { index: "z", set: "zone" }, via: "adjacent" }, severity: "hard" }, "ir_opaque_rule"],
];

describe("constructs without a block of their own yet", () => {
  it.each(CASES)("%s is carried verbatim and named", (_name, rule, type) => {
    const ir = { version: 2, sets: [], parameters: {}, variables: {}, constraints: [rule] };
    const blocks = [...walk(irToBlocks(ir).blocks.blocks[0])];
    const carrier = blocks.find((b) => b.type === type)!;
    expect(carrier.fields!.LABEL).toMatch(/kept as it is/);
    expect(blocks.some((b) => JSON.stringify(b).includes("no expression"))).toBe(false);
    expect(blocksToIr(irToBlocks(ir)).ir.constraints).toEqual([rule]);
  });
});
