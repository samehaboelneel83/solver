import * as Blockly from "blockly";
import { beforeAll, describe, expect, it } from "vitest";
import { EMPTY_CATALOGUE, scopeAt, setCatalogue } from "./catalogue";
import { defineIrBlocks, loadBlocks } from "./vocabulary";

const CATALOGUE = {
  entityTypes: [
    { name: "employee", attributes: [{ name: "hours", data_type: "integer" }, { name: "name", data_type: "text" }] },
    { name: "day", attributes: [] },
  ],
  parameters: [{ name: "demand", index: ["day"] }],
  relationships: [{ name: "works_with", from: "employee", to: "employee" }],
};

function options(block: Blockly.Block, field: string): string[] {
  return (block.getField(field) as Blockly.FieldDropdown).getOptions(false).map(([, value]) => value as string);
}

function load(blocks: object[]): Blockly.Workspace {
  const ws = new Blockly.Workspace();
  setCatalogue(ws, CATALOGUE);
  loadBlocks(ws, { blocks: { languageVersion: 0, blocks } });
  return ws;
}

const MODEL = (rules: object, declare?: object) => ({
  type: "ir_model", id: "model-root", extraState: { version: 2 },
  inputs: { ...(declare ? { DECLARE: { block: declare } } : {}), RULES: { block: rules } },
});

beforeAll(() => defineIrBlocks());

describe("what a block offers", () => {
  it("offers a data block only the indices bound to the set its parameter expects", () => {
    const par = { type: "ir_par", id: "p", extraState: { arity: 1 }, fields: { NAME: "demand", IDX0: "d" } };
    const ws = load([MODEL(
      { type: "ir_rule", id: "r", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
        inputs: {
          FORALL: { block: { type: "ir_binding", fields: { INDEX: "e", SET: "employee" },
            next: { block: { type: "ir_binding", fields: { INDEX: "d", SET: "day" } } } } },
          LEFT: { block: par } } },
      { type: "ir_parameter", fields: { NAME: "demand" }, extraState: { index: ["day"] } },
    )]);
    const block = ws.getBlockById("p")!;
    expect([...scopeAt(block)]).toEqual([["e", "employee"], ["d", "day"]]);
    expect(options(block, "IDX0")).toEqual(["d"]);
  });

  it("offers inside a sum's body the sum's own indices too, and not outside it", () => {
    const ws = load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_sum", id: "s",
        inputs: { OVER: { block: { type: "ir_binding", fields: { INDEX: "e", SET: "employee" } } },
                  BODY: { block: { type: "ir_attr", id: "a", fields: { OF: "e", NAME: "hours" } } } } } },
        RIGHT: { block: { type: "ir_attr", id: "b", fields: { OF: "", NAME: "" } } } } })]);
    expect(options(ws.getBlockById("a")!, "OF")).toEqual(["e"]);
    expect(options(ws.getBlockById("a")!, "NAME")).toEqual(["hours"]); // a number: text attributes are not offered
    expect(options(ws.getBlockById("b")!, "OF")).toEqual([""]);
  });

  it("keeps a value that is no longer offered, rather than blanking it (Review Focus 2, 5)", () => {
    const ws = load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "gone" } } } } },
      { type: "ir_set", id: "set", fields: { SET: "renamed_type" } })]);
    expect(ws.getBlockById("v")!.getFieldValue("NAME")).toBe("gone");
    expect(ws.getBlockById("set")!.getFieldValue("SET")).toBe("renamed_type");
    expect(options(ws.getBlockById("set")!, "SET")).toContain("renamed_type");
  });

  it("reshapes a decision's index slots with its arity, and saves the shape", () => {
    const ws = load([{ type: "ir_variable", id: "x", extraState: { arity: 1 }, fields: { NAME: "x", SET0: "day", DOMAIN: "binary" } }]);
    const block = ws.getBlockById("x")!;
    block.setFieldValue("2", "ARITY");
    block.setFieldValue("employee", "SET1");
    const saved = Blockly.serialization.blocks.save(block) as unknown as { extraState: unknown; fields: Record<string, string> };
    expect(saved.extraState).toEqual({ arity: 2 });
    expect([saved.fields.SET0, saved.fields.SET1]).toEqual(["day", "employee"]);
  });

  it("shows a rule's weight only when the rule is soft", () => {
    const ws = load([{ type: "ir_rule", id: "r", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" } }]);
    const rule = ws.getBlockById("r")!;
    expect(rule.getField("WEIGHT")!.isVisible()).toBe(false);
    rule.setFieldValue("soft", "SEVERITY");
    expect(rule.getField("WEIGHT")!.isVisible()).toBe(true);
  });

  it("refuses a name the platform would refuse, and a name already declared", () => {
    const ws = load([
      { type: "ir_variable", id: "a", extraState: { arity: 0 }, fields: { NAME: "x", DOMAIN: "binary" } },
      { type: "ir_variable", id: "b", extraState: { arity: 0 }, fields: { NAME: "y", DOMAIN: "binary" } },
    ]);
    const b = ws.getBlockById("b")!;
    b.setFieldValue("Bad Name", "NAME");
    expect(b.getFieldValue("NAME")).toBe("y");
    b.setFieldValue("x", "NAME");
    expect(b.getFieldValue("NAME")).toBe("y");
  });

  it("loads an unchosen dropdown as NONE and saves it back", () => {
    const ws = load([{ type: "ir_set", id: "s", fields: { SET: "" } }]);
    setCatalogue(ws, EMPTY_CATALOGUE);
    expect((Blockly.serialization.blocks.save(ws.getBlockById("s")!) as unknown as { fields: { SET: string } }).fields.SET).toBe("");
  });
});

describe("a new block from the toolbox", () => {
  it("starts from the first choice of every fixed list, not from nothing", () => {
    const ws = new Blockly.Workspace();
    const rule = ws.newBlock("ir_rule");
    expect([rule.getFieldValue("SEVERITY"), rule.getFieldValue("RELATION")]).toEqual(["hard", "<="]);
    expect(ws.newBlock("ir_variable").getFieldValue("DOMAIN")).toBe("binary");
    expect(ws.newBlock("ir_model").getFieldValue("SENSE")).toBe("minimize");
  });
});
