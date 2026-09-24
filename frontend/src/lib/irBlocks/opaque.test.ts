import { describe, expect, it } from "vitest";
import { irToBlocks, type SerialBlock } from "./toBlocks";
import { blocksToIr } from "./toIr";

/**
 * Every construct has its own block (Blocks 3); a shape the blocks could not
 * write back exactly -- a construct added to the contract later, or one the
 * blocks do not write that way -- still travels in an opaque block carrying
 * it verbatim: shown by name, not editable here, never lost.
 */
function* walk(block: SerialBlock): Generator<SerialBlock> {
  yield block;
  for (const input of Object.values(block.inputs ?? {})) yield* walk(input.block);
  if (block.next) yield* walk(block.next.block);
}

const X = { var: "x", index: [] };
const OWN: [string, Record<string, unknown>, string][] = [
  ["a piecewise curve", { id: "c", left: { pwl: { var: "units", index: ["p"] }, points: [[0, 0], [2, 10]] }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_pwl"],
  ["a function", { id: "c", left: { fn: "log", of: { add: [{ const: 1 }, X] } }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_fn"],
  ["a scheduling rule", { id: "c_room", no_overlap: { interval: { var: "task", index: ["j"] }, over: [{ index: "j", set: "job" }] }, severity: "hard" }, "ir_no_overlap"],
  ["a conditional rule", { id: "c_closed", left: X, relation: "<=", right: { const: 0 }, severity: "hard", when: { var: "open", index: [], is: 0 } }, "ir_when"],
  ["a connected rule", { id: "c_zones", connected: { assign: { var: "assign", index: ["u", "z"] }, units: { index: "u", set: "cell" }, groups: { index: "z", set: "zone" }, via: "adjacent" }, severity: "hard" }, "ir_connected"],
];

const KEPT: [string, Record<string, unknown>, string][] = [
  ["a term kind the blocks do not know", { id: "c", left: { cube: X }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_opaque_term"],
  ["a connected rule whose decision is read [group, unit]", { id: "c_zones", connected: { assign: { var: "assign", index: ["z", "u"] }, units: { index: "u", set: "cell" }, groups: { index: "z", set: "zone" }, via: "adjacent" }, severity: "hard" }, "ir_opaque_rule"],
  ["a curve with more points than a block holds", { id: "c", left: { pwl: X, points: Array.from({ length: 13 }, (_, k) => [k, k]) }, relation: "<=", right: { const: 1 }, severity: "hard" }, "ir_opaque_term"],
];

const model = (rule: Record<string, unknown>) => ({ version: 2, sets: [], parameters: {}, variables: {}, constraints: [rule] });

describe("every construct has its own block", () => {
  it.each(OWN)("%s", (_name, rule, type) => {
    const ir = model(rule);
    const blocks = [...walk(irToBlocks(ir).blocks.blocks[0])];
    expect(blocks.map((b) => b.type)).toContain(type);
    expect(blocks.some((b) => b.type.startsWith("ir_opaque_"))).toBe(false);
    expect(blocksToIr(irToBlocks(ir)).ir.constraints).toEqual([rule]);
  });
});

describe("a shape the blocks could not write back exactly", () => {
  it.each(KEPT)("%s is carried verbatim and named", (_name, rule, type) => {
    const ir = model(rule);
    const carrier = [...walk(irToBlocks(ir).blocks.blocks[0])].find((b) => b.type === type)!;
    expect(carrier.fields!.LABEL).toMatch(/kept as it is/);
    expect(blocksToIr(irToBlocks(ir)).ir.constraints).toEqual([rule]);
  });
});
