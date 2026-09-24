import { describe, expect, it } from "vitest";
import { checkIrShape } from "../../ir";
import { blockForLoc, blocksToIr } from "./toIr";

const WS = { blocks: { blocks: [{ type: "ir_model", id: "model-root", extraState: { version: 2 },
  inputs: {
    DECLARE: { block: { type: "ir_variable", id: "x", extraState: { arity: 0 }, fields: { NAME: "x", ARITY: "0", DOMAIN: "binary", LOWER: "", UPPER: "" } } },
    RULES: { block: { type: "ir_rule", id: "r", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_mul", id: "m", inputs: { A: { block: { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "x" } } } } } },
                RIGHT: { block: { type: "ir_const", id: "k", fields: { VALUE: "1" } } } } } } } }] } };

describe("a refusal lands on the block that caused it", () => {
  it("an empty socket: the product whose second factor is missing", () => {
    const { ir, paths } = blocksToIr(WS);
    const refusal = checkIrShape(ir)!;
    expect(refusal.code).toBe("const_not_a_number");
    expect(blockForLoc(paths, refusal.loc)).toBe("m");
  });

  it("a stale reference: the decision block that names a deleted decision (Review Focus 2)", () => {
    const stale = JSON.parse(JSON.stringify(WS));
    stale.blocks.blocks[0].inputs.DECLARE.block.fields.NAME = "y";
    stale.blocks.blocks[0].inputs.RULES.block.inputs.LEFT.block = { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "x" } };
    const { ir, paths } = blocksToIr(stale);
    const refusal = checkIrShape(ir)!;
    expect(refusal.code).toBe("reference_undeclared");
    expect(blockForLoc(paths, refusal.loc)).toBe("v");
  });

  it("a refusal about the model as a whole lands on the model", () => {
    const { paths } = blocksToIr(WS);
    expect(blockForLoc(paths, ["objective"])).toBeNull();
    expect(blockForLoc(paths, ["variables", "x", "domain"])).toBe("x");
  });
});
