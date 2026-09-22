import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { EntityType } from "../api/v1";
import { BLOCK_DEFINITIONS, modelToBlocks, partOfBlock, termBlock, type SerialBlock } from "./modelBlocks";
import { buildModelView, OBJECTIVE_NODE_ID } from "./modelGraph";
import { layoutModel } from "./modelLayout";
import { reteNodes } from "./modelNodes";

/**
 * The three extra drawing styles of the optimization view, on the seeded
 * workforce model (the IR contract's own worked example, read off disk).
 * The components themselves need a browser; what they draw from is here.
 */

const FIXTURE_PATH = (() => {
  const relative = "backend/tests/ir_fixtures.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

const WORKFORCE = (
  JSON.parse(readFileSync(FIXTURE_PATH, "utf-8")) as { valid: { name: string; ir: Record<string, unknown> }[] }
).valid.find((fixture) => fixture.name === "workforce")!.ir;

const type = (id: number, name: string): EntityType => ({
  id,
  domain_id: 1,
  name,
  role: "other",
  colour: null,
  icon: null,
  updated_at: "2026-09-22T00:00:00+00:00",
  attributes: [],
});
const { graph } = buildModelView(WORKFORCE, [type(1, "employee"), type(2, "unit"), type(3, "day"), type(4, "shift")]);

function* walk(block: SerialBlock): Generator<SerialBlock> {
  yield block;
  for (const input of Object.values(block.inputs ?? {})) yield* walk(input.block);
  if (block.next) yield* walk(block.next.block);
}

describe("Blockly: the model as blocks", () => {
  const workspace = modelToBlocks(WORKFORCE, graph, "weekly_rota");
  const [root] = workspace.blocks.blocks;
  const all = [...walk(root)];

  it("defines a block for every kind it uses", () => {
    const defined = new Set(BLOCK_DEFINITIONS.map((definition) => definition.type));
    for (const block of all) expect(defined.has(block.type), block.type).toBe(true);
  });

  it("gives every part of the model its node id, so a click selects the same thing", () => {
    const ids = new Set(all.map((block) => block.id).filter(Boolean));
    for (const node of graph.nodes) expect(ids.has(node.id), node.id).toBe(true);
  });

  it("draws a rule as its 'for every' and its two sides", () => {
    const cover = all.find((block) => block.id === "model-con-c_cover_demand")!;
    expect(cover.type).toBe("ir_rule_hard");
    expect(cover.fields).toMatchObject({ ID: "c_cover_demand", FORALL: "d in day, s in shift", RELATION: "≥" });
    const left = cover.inputs!.LEFT.block;
    expect(left.type).toBe("ir_sum");
    expect(left.fields!.OVER).toBe("e in employee");
    expect(left.inputs!.BODY.block).toMatchObject({ type: "ir_var", fields: { NAME: "assign", INDEX: "[e, d, s]" } });
    expect(cover.inputs!.RIGHT.block).toMatchObject({ type: "ir_par", fields: { NAME: "demand", INDEX: "[d, s]" } });
  });

  it("marks a rule that may bend, with its price", () => {
    const soft = all.find((block) => block.id === "model-con-c_north_region_lates")!;
    expect(soft.type).toBe("ir_rule_soft");
    expect(soft.fields!.PRICE).toBe("4");
  });

  it("stacks the goal's terms under it", () => {
    const goal = all.find((block) => block.id === OBJECTIVE_NODE_ID)!;
    expect(goal.fields!.SENSE).toBe("minimize");
    expect(goal.inputs!.TERMS.block.type).toBe("ir_goal_term");
  });

  it("is read-only: nothing moves, edits or deletes", () => {
    for (const block of all) expect([block.movable, block.editable, block.deletable]).toEqual([false, false, false]);
  });

  it("draws a sum of three as nested pluses, and a product as its two factors", () => {
    const x = { var: "x", index: [] };
    const sum = termBlock({ add: [x, { const: 2 }, x] });
    expect(sum.type).toBe("ir_add");
    expect(sum.inputs!.B.block.type).toBe("ir_add");
    expect(termBlock({ mul: [{ const: 3 }, x] }).inputs!.A.block.fields!.VALUE).toBe("3");
  });

  it("draws a rule published before the IR contract without failing", () => {
    const old = modelToBlocks({ constraints: [{ id: "c_old" }] }, buildModelView({}, []).graph);
    const rule = [...walk(old.blocks.blocks[0])].find((block) => block.id === "model-con-c_old")!;
    expect(rule.fields!.RELATION).toBe("(no expression)");
    expect(rule.inputs).toEqual({});
  });

  it("selects the part a clicked term belongs to", () => {
    const parents: Record<string, string> = { t2: "t1", t1: "model-con-c", "model-con-c": "model-root" };
    const known = new Set(["model-con-c"]);
    expect(partOfBlock("t2", (id) => parents[id] ?? null, known)).toBe("model-con-c");
    expect(partOfBlock("model-root", (id) => parents[id] ?? null, known)).toBeNull();
  });
});

describe("Rete.js and React Flow: nodes with inputs and an output", () => {
  const specs = new Map(reteNodes(graph).map((spec) => [spec.id, spec]));

  it("gives a rule one input per thing it reads, naming an attribute read as a number", () => {
    const hours = specs.get("model-con-c_max_hours")!;
    expect(hours.inputs.map((input) => input.label)).toContain("employee · hours_per_week");
    expect(hours.inputs.map((input) => input.from)).toContain("model-var-assign");
  });

  it("gives an output only to a part that feeds another, named for what it supplies", () => {
    expect(specs.get("type-1")!.output).toBe("members");
    expect(specs.get("model-var-assign")!.output).toBe("decision");
    expect(specs.get("model-con-c_north_region_lates")!.output).toBe("penalty");
    expect(specs.get("model-con-c_max_hours")!.output).toBeNull();
    expect(specs.get(OBJECTIVE_NODE_ID)!.output).toBeNull();
  });

  it("carries each part's key fact", () => {
    expect(specs.get("model-var-assign")!.summary).toBe("0 or 1");
    expect(specs.get("model-con-c_cover_demand")!.summary).toMatch(/≥ demand\[d, s\]/);
  });
});

describe("the column layout", () => {
  const boxes = layoutModel(graph, () => ({ width: 100, height: 50 }), { columnGap: 20, rowGap: 10 });
  const x = (id: string) => boxes.get(id)!.x;

  it("reads left to right: sets, then decisions and data, then rules, then the goal", () => {
    expect(x("type-1")).toBeLessThan(x("model-var-assign"));
    expect(x("model-var-assign")).toBe(x("model-par-demand"));
    expect(x("model-par-demand")).toBeLessThan(x("model-con-c_cover_demand"));
    expect(x("model-con-c_cover_demand")).toBeLessThan(x(OBJECTIVE_NODE_ID));
  });

  it("places every node, and no two in a column overlap", () => {
    expect(boxes.size).toBe(graph.nodes.length);
    const byColumn = new Map<number, { y: number; height: number }[]>();
    for (const box of boxes.values()) byColumn.set(box.x, [...(byColumn.get(box.x) ?? []), box]);
    for (const column of byColumn.values()) {
      const sorted = column.sort((a, b) => a.y - b.y);
      for (let i = 1; i < sorted.length; i += 1) {
        expect(sorted[i].y).toBeGreaterThanOrEqual(sorted[i - 1].y + sorted[i - 1].height);
      }
    }
  });
});
