import * as Blockly from "blockly";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { showIr } from "../../components/BlocksEditor";
import { checkIrShape } from "../../ir";
import { EMPTY_MODEL } from "../../model/draftIr";
import { setCatalogue } from "./catalogue";
import { blocksToIr } from "./toIr";
import { defineIrBlocks } from "./vocabulary";

/**
 * The spec's "builds the feed-blend model from an empty draft by blocks
 * alone" (Blockly edit mode, Task 9), run where it can be exact: every block
 * made and connected through the calls a person's drags and picks perform
 * -- `newBlock`, `setFieldValue` (validators on, as for a person), connecting
 * -- and the IR the workspace then makes is the template's own.
 */
function above(relative: string): string {
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} not found`);
  }
}
const FEED_BLEND = (JSON.parse(readFileSync(above("backend/tests/template_irs.json"), "utf8")) as Record<string, Record<string, unknown>>).feed_blend;

const CATALOGUE = {
  entityTypes: [{ name: "feed", attributes: [{ name: "protein", data_type: "number" }, { name: "fibre", data_type: "number" }] }],
  parameters: [{ name: "cost", index: ["feed"] }],
  relationships: [],
};

beforeAll(() => defineIrBlocks());

describe("the feed-blend model, built block by block from an empty draft", () => {
  it("makes exactly the template's model", () => {
    const ws = new Blockly.Workspace();
    setCatalogue(ws, CATALOGUE);
    showIr(ws, EMPTY_MODEL as unknown as Record<string, unknown>);
    const root = ws.getBlockById("model-root")!;

    const make = (type: string, fields: Record<string, string> = {}) => {
      const block = ws.newBlock(type);
      for (const [name, value] of Object.entries(fields)) block.setFieldValue(value, name);
      return block;
    };
    const stackOnto = (input: Blockly.Input | Blockly.Block, blocks: Blockly.Block[]) => {
      let connection = input instanceof Blockly.Block ? input.nextConnection! : input.connection!;
      for (const block of blocks) {
        connection.connect(block.previousConnection!);
        connection = block.nextConnection!;
      }
    };
    const plug = (block: Blockly.Block, input: string, value: Blockly.Block) => block.getInput(input)!.connection!.connect(value.outputConnection!);
    const use = () => make("ir_var", { NAME: "use", IDX0: "f" });
    const sumOverFeeds = (body: Blockly.Block) => {
      const sum = make("ir_sum");
      stackOnto(sum.getInput("OVER")!, [make("ir_binding", { INDEX: "f", SET: "feed" })]);
      plug(sum, "BODY", body);
      return sum;
    };
    const times = (a: Blockly.Block, b: Blockly.Block) => {
      const mul = make("ir_mul");
      plug(mul, "A", a);
      plug(mul, "B", b);
      return mul;
    };
    const rule = (id: string, note: string, relation: string, left: Blockly.Block, right: string) => {
      const r = make("ir_rule", { ID: id, NOTE: note, RELATION: relation });
      plug(r, "LEFT", left);
      plug(r, "RIGHT", make("ir_const", { VALUE: right }));
      return r;
    };

    // Declarations: the set, the decision (one index, continuous, 0..100), the data (its index from the domain).
    const decision = make("ir_variable", { NAME: "use", ARITY: "1" });
    decision.setFieldValue("feed", "SET0");
    decision.setFieldValue("continuous", "DOMAIN");
    decision.setFieldValue("0", "LOWER");
    decision.setFieldValue("100", "UPPER");
    stackOnto(root.getInput("DECLARE")!, [make("ir_set", { SET: "feed" }), decision, make("ir_parameter", { NAME: "cost" })]);

    stackOnto(root.getInput("RULES")!, [
      rule("c_batch", "the batch is exactly 100 kg", "=", sumOverFeeds(use()), "100"),
      rule("c_protein", "at least 20 kg of protein in the batch", ">=", sumOverFeeds(times(make("ir_attr", { OF: "f", NAME: "protein" }), use())), "20"),
      rule("c_fibre", "at most 5 kg of fibre in the batch", "<=", sumOverFeeds(times(make("ir_attr", { OF: "f", NAME: "fibre" }), use())), "5"),
    ]);

    const goal = make("ir_goal_term", { ID: "o_cost", WEIGHT: "1" });
    plug(goal, "EXPRESSION", sumOverFeeds(times(make("ir_par", { NAME: "cost", IDX0: "f" }), use())));
    stackOnto(root.getInput("GOAL")!, [goal]);

    const { ir, outside } = blocksToIr(Blockly.serialization.workspaces.save(ws) as Parameters<typeof blocksToIr>[0]);
    expect(outside).toBe(0);
    expect(checkIrShape(ir)).toBeNull();
    // A model started from blocks is written in the current contract version; the template predates it.
    expect(ir.version).toBe(2);
    expect({ ...ir, version: FEED_BLEND.version }).toEqual(FEED_BLEND);
  });
});
