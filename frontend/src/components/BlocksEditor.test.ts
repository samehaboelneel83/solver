import * as Blockly from "blockly";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { setCatalogue } from "../lib/irBlocks/catalogue";
import { defineIrBlocks, toolboxFor } from "../lib/irBlocks/vocabulary";
import { bindWorkspace, showIr } from "./BlocksEditor";

const IR = { version: 2, sets: ["day"], parameters: {}, variables: { x: { index: ["day"], domain: "binary" } }, constraints: [] };
const now = (run: () => void) => run();
/** Long enough for Blockly's queued change events to have fired. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

beforeAll(() => defineIrBlocks());

function workspace() {
  const ws = new Blockly.Workspace();
  setCatalogue(ws, { entityTypes: [{ name: "day", attributes: [] }], parameters: [], relationships: [] });
  return ws;
}

describe("the Blocks editor's workspace", () => {
  it("shows the draft without reporting it as an edit", async () => {
    const ws = workspace();
    const onChange = vi.fn();
    bindWorkspace(ws, onChange, now);
    showIr(ws, IR);
    await settle();
    expect(onChange).not.toHaveBeenCalled();
    expect(ws.getBlockById("model-root")).not.toBeNull();
  });

  it("reports an edit as the whole IR, with where each block landed", async () => {
    const ws = workspace();
    showIr(ws, IR);
    const onChange = vi.fn();
    bindWorkspace(ws, onChange, now);
    ws.getBlockById("model-root")!.setFieldValue("maximize", "SENSE");
    const rule = ws.newBlock("ir_rule");
    ws.getBlockById("model-root")!.getInput("RULES")!.connection!.connect(rule.previousConnection!);
    await vi.waitFor(() => expect(onChange.mock.calls.at(-1)?.[0].constraints).toHaveLength(1));
    const [ir, paths, outside] = onChange.mock.calls.at(-1)!;
    expect(ir.variables).toEqual(IR.variables);
    expect(ir.constraints).toHaveLength(1);
    expect(paths.get(rule.id)).toEqual(["constraints", 0]);
    expect(outside).toBe(0);
  });

  it("counts a block left beside the model, not in it", async () => {
    const ws = workspace();
    showIr(ws, IR);
    const onChange = vi.fn();
    bindWorkspace(ws, onChange, now);
    ws.newBlock("ir_rule");
    await vi.waitFor(() => expect(onChange.mock.calls.at(-1)?.[2]).toBe(1));
  });

  it("coalesces a burst of events into one report", async () => {
    const ws = workspace();
    showIr(ws, IR);
    const queued: (() => void)[] = [];
    const onChange = vi.fn();
    bindWorkspace(ws, onChange, (run) => queued.push(run));
    ws.getBlockById("model-root")!.setFieldValue("maximize", "SENSE");
    ws.getBlockById("model-root")!.setFieldValue("lex", "MODE");
    await vi.waitFor(() => expect(queued.length).toBeGreaterThan(0));
    // Give the rest of the burst time to arrive: it must join the one report.
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(queued).toHaveLength(1);
    queued[0]();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("offers in the toolbox only what the domain can fill", () => {
    const empty = JSON.stringify(toolboxFor({ entityTypes: [], parameters: [], relationships: [] }));
    expect(empty).not.toContain('"ir_set"');
    expect(empty).not.toContain('"ir_par"');
    expect(empty).toContain('"ir_rule"');
    const full = JSON.stringify(toolboxFor({ entityTypes: [{ name: "feed", attributes: [{ name: "protein", data_type: "number" }] }], parameters: [{ name: "cost", index: ["feed"] }], relationships: [] }));
    for (const type of ["ir_set", "ir_par", "ir_attr", "ir_filter", "ir_binding"]) expect(full).toContain(`"${type}"`);
  });
});
