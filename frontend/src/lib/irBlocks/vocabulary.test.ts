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
  relationships: [{ name: "works_with", from: "employee", to: "employee",
    attributes: [{ name: "overlap", data_type: "number" }, { name: "note", data_type: "text" }] }],
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

  it("offers an edge a via names, its declared numbers, and a path's combination (queue R19)", () => {
    const walk = (depth: string) => load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: {
        FORALL: { block: { type: "ir_binding", fields: { INDEX: "a", SET: "employee" } } },
        LEFT: { block: { type: "ir_sum", id: "s",
          inputs: { OVER: { block: { type: "ir_binding", fields: { INDEX: "b", SET: "employee", VIA_REL: "works_with",
            VIA_END: "from", VIA_ANCHOR: "a", VIA_DEPTH: depth, VIA_AS: "w" } } },
                    BODY: { block: { type: "ir_attr", id: "x", fields: { OF: "w", NAME: "overlap" } } } } } } } })]);
    const one = walk("").getBlockById("x")!;
    expect([...scopeAt(one)]).toEqual([["a", "employee"], ["b", "employee"], ["w", "@works_with/one"]]);
    expect(options(one, "NAME")).toEqual(["overlap"]); // a number the type declares for its edges
    one.onchange?.(new Blockly.Events.BlockChange(one, "field", "OF", "w", "w"));
    expect(one.getField("ALONG")!.isVisible()).toBe(false); // one edge, one value
    const path = walk("any").getBlockById("x")!;
    path.onchange?.(new Blockly.Events.BlockChange(path, "field", "OF", "w", "w"));
    expect(path.getField("ALONG")!.isVisible()).toBe(true);
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

describe("what a dropdown shows", () => {
  it("shows the value it holds even when nothing offers it (the read-only view has no catalogue)", () => {
    const ws = load([
      { type: "ir_set", id: "set", fields: { SET: "feed" } },
      { type: "ir_parameter", id: "par", fields: { NAME: "cost" }, extraState: { index: ["feed"] } },
      { type: "ir_variable", id: "var", extraState: { arity: 1 }, fields: { NAME: "use", ARITY: "1", SET0: "feed", DOMAIN: "continuous" } },
    ]);
    setCatalogue(ws, EMPTY_CATALOGUE);
    expect(ws.getBlockById("set")!.getField("SET")!.getText()).toBe("feed");
    expect(ws.getBlockById("par")!.getField("NAME")!.getText()).toBe("cost");
    expect(ws.getBlockById("var")!.getField("SET0")!.getText()).toBe("feed");
  });
});

describe("the advanced constructs' blocks (Blocks 3)", () => {
  const DECLARE = {
    type: "ir_variable", fields: { NAME: "open", ARITY: "1", SET0: "day", DOMAIN: "binary" }, extraState: { arity: 1 },
    next: { block: {
      type: "ir_variable", fields: { NAME: "hours", ARITY: "1", SET0: "day", DOMAIN: "integer", LOWER: "0", UPPER: "8" }, extraState: { arity: 1 },
      next: { block: {
        type: "ir_variable", fields: { NAME: "assign", ARITY: "2", SET0: "employee", SET1: "day", DOMAIN: "binary" }, extraState: { arity: 2 },
        next: { block: {
          type: "ir_variable", fields: { NAME: "shift", ARITY: "1", SET0: "day", DOMAIN: "interval", START: "hours", END: "hours", SIZE: "4" }, extraState: { arity: 1 },
        } },
      } },
    } },
  };

  it("a condition offers only yes-or-no decisions, and only the indices its rule binds", () => {
    const ws = load([MODEL(
      { type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
        inputs: {
          FORALL: { block: { type: "ir_binding", fields: { INDEX: "d", SET: "day" } } },
          WHEN: { block: { type: "ir_when", id: "w", fields: { VAR: "open", IDX0: "d", IS: "0" }, extraState: { arity: 1, isGiven: true } } },
        } },
      DECLARE,
    )]);
    const w = ws.getBlockById("w")!;
    expect(options(w, "VAR")).toEqual(["open", "assign"]);
    expect(options(w, "IDX0")).toEqual(["d"]);
  });

  it("a connected rule offers only decisions of two different sets, and relationships of its units to themselves", () => {
    const ws = load([MODEL(
      { type: "ir_connected", id: "k", fields: { ID: "c", VAR: "assign", U_INDEX: "e", U_SET: "employee", Z_INDEX: "d", Z_SET: "day", VIA: "works_with", EMPTY: "forbidden" }, extraState: { emptyGiven: false } },
      DECLARE,
    )]);
    const k = ws.getBlockById("k")!;
    expect(options(k, "VAR")).toEqual(["assign"]);
    expect(options(k, "VIA")).toEqual(["works_with"]);
  });

  it("choosing a connected rule's decision fills in its units and groups", () => {
    const ws = load([MODEL(
      { type: "ir_connected", id: "k", fields: { ID: "c", VAR: "", U_INDEX: "", U_SET: "", Z_INDEX: "", Z_SET: "", VIA: "", EMPTY: "forbidden" }, extraState: { emptyGiven: false } },
      DECLARE,
    )]);
    const k = ws.getBlockById("k")!;
    k.setFieldValue("assign", "VAR");
    expect(["U_INDEX", "U_SET", "Z_INDEX", "Z_SET"].map((f) => k.getFieldValue(f))).toEqual(["e", "employee", "d", "day"]);
  });

  it("a function lists every function of the catalogue with its curvature", () => {
    const ws = load([MODEL({ type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
      inputs: { LEFT: { block: { type: "ir_fn", id: "f", fields: { NAME: "log" } } } } })]);
    const labels = (ws.getBlockById("f")!.getField("NAME") as Blockly.FieldDropdown).getOptions(false).map(([label]) => label);
    expect(labels).toEqual(["exp — convex", "log — concave", "sqrt — concave", "abs — convex", "sin — neither", "cos — neither"]);
  });

  it("a cumulative's demand sees its OVER indices; its capacity does not", () => {
    const ws = load([MODEL(
      { type: "ir_cumulative", id: "cu", fields: { ID: "c", INTERVAL: "shift", IDX0: "d" }, extraState: { arity: 1 },
        inputs: {
          OVER: { block: { type: "ir_binding", fields: { INDEX: "d", SET: "day" } } },
          DEMAND: { block: { type: "ir_attr", id: "dem", fields: { OF: "", NAME: "" } } },
          CAPACITY: { block: { type: "ir_attr", id: "cap", fields: { OF: "", NAME: "" } } },
        } },
      DECLARE,
    )]);
    expect([...scopeAt(ws.getBlockById("dem")!).keys()]).toEqual(["d"]);
    expect([...scopeAt(ws.getBlockById("cap")!).keys()]).toEqual([]);
    // Its own interval slots read its OVER, and it offers only interval decisions.
    expect(options(ws.getBlockById("cu")!, "IDX0")).toEqual(["d"]);
    expect(options(ws.getBlockById("cu")!, "INTERVAL")).toEqual(["shift"]);
  });

  it("an interval's start and end offer integer decisions with its own index; a plain reference never names an interval", () => {
    const ws = load([MODEL(
      { type: "ir_rule", fields: { ID: "c", SEVERITY: "hard", RELATION: "<=" },
        inputs: { LEFT: { block: { type: "ir_var", id: "v", extraState: { arity: 0 }, fields: { NAME: "" } } } } },
      DECLARE,
    )]);
    const shift = ws.getAllBlocks(false).find((b) => b.type === "ir_variable" && b.getFieldValue("NAME") === "shift")!;
    expect(options(shift, "START")).toEqual(["hours"]);
    expect(options(shift, "PRESENCE")).toEqual(["", "open"]);
    expect(options(ws.getBlockById("v")!, "NAME")).not.toContain("shift");
  });
});

describe("an entity-valued parameter's cell as slot text (queue R20b)", () => {
  it("writes and reads back a cell, nested or not, and leaves an index name alone", async () => {
    const { cellText, parseCell } = await import("./catalogue");
    const cell = { par: "preferred_shift", index: ["e", { par: "home_day", index: ["e"] }] };
    expect(cellText(cell)).toBe("preferred_shift[e, home_day[e]]");
    expect(parseCell(cellText(cell))).toEqual(cell);
    expect(parseCell("d")).toBe("d");
  });
});
