import * as Blockly from "blockly";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { EMPTY_CATALOGUE, setCatalogue } from "./catalogue";
import { blocksToIr } from "./toIr";
import { irToBlocks } from "./toBlocks";
import { defineIrBlocks, loadBlocks } from "./vocabulary";

function above(relative: string): string {
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} not found`);
  }
}
const FIXTURES = JSON.parse(readFileSync(above("backend/tests/ir_fixtures.json"), "utf8")) as { valid: { name: string; ir: Record<string, unknown> }[] };
const TEMPLATES = JSON.parse(readFileSync(above("backend/tests/template_irs.json"), "utf8")) as Record<string, Record<string, unknown>>;
const CASES: [string, Record<string, unknown>][] = [
  ...FIXTURES.valid.map((f) => [`fixture ${f.name}`, f.ir] as [string, Record<string, unknown>]),
  ...Object.entries(TEMPLATES).map(([name, ir]) => [`template ${name}`, ir] as [string, Record<string, unknown>]),
];

/** The only two differences the blocks may make, both without meaning. */
function canonical(ir: Record<string, unknown>): Record<string, unknown> {
  const out = JSON.parse(JSON.stringify(ir));
  if (Array.isArray(out.relationships)) out.relationships = [...out.relationships].sort();
  if (out.objective?.mode === "weighted") delete out.objective.mode;
  return out;
}

/** Through a real (headless) workspace, as the editor does -- not only data to data. */
function throughWorkspace(ir: Record<string, unknown>) {
  const ws = new Blockly.Workspace();
  setCatalogue(ws, EMPTY_CATALOGUE); // Review Focus 5: no option list holds any of these values
  loadBlocks(ws, irToBlocks(ir, { editable: true }));
  const saved = Blockly.serialization.workspaces.save(ws);
  ws.dispose();
  return blocksToIr(saved as Parameters<typeof blocksToIr>[0]);
}

beforeAll(() => defineIrBlocks());

describe("blocks round-trip every model exactly", () => {
  it.each(CASES)("%s", (_name, ir) => {
    const { ir: back, outside } = throughWorkspace(ir);
    expect(outside).toBe(0);
    expect(canonical(back)).toEqual(canonical(ir));
  });

  it("needs no opaque block for any of them: every construct has its own block (Blocks 3)", () => {
    for (const [name, ir] of CASES) {
      expect(JSON.stringify(irToBlocks(ir, { editable: true })), name).not.toMatch(/"type":"ir_opaque_/);
    }
  });

  it("covers every fixture and template (a new one is picked up, not skipped)", () => {
    expect(CASES.length).toBe(FIXTURES.valid.length + Object.keys(TEMPLATES).length);
    expect(CASES.length).toBeGreaterThanOrEqual(28);
  });
});

describe("blocksToIr", () => {
  it("edits scenario futures without an opaque declaration and preserves optional labels", () => {
    const ir = { version: 2, sets: [], parameters: { demand: { index: [], uncertainty: {
      kind: "scenarios", futures: [{ factor: 0.8 }, { label: "", factor: 1 }, { label: "busy", factor: 1.25 }],
    } } }, variables: {}, constraints: [] };
    const ws = new Blockly.Workspace();
    try {
      setCatalogue(ws, EMPTY_CATALOGUE);
      loadBlocks(ws, irToBlocks(ir, { editable: true }));
      const futures = ws.getAllBlocks(false).filter((block) => block.type === "ir_future");
      expect(futures).toHaveLength(3);
      const busy = futures.find((block) => block.getFieldValue("LABEL") === "busy")!;
      busy.setFieldValue("1.5", "FACTOR");
      const saved = Blockly.serialization.workspaces.save(ws);
      const result = blocksToIr(saved as Parameters<typeof blocksToIr>[0]);
      expect(result.ir.parameters).toEqual({ demand: { index: [], uncertainty: {
        kind: "scenarios", futures: [{ factor: 0.8 }, { label: "", factor: 1 }, { label: "busy", factor: 1.5 }],
      } } });
      expect(result.paths.get(busy.id)).toEqual(["parameters", "demand", "uncertainty", "futures", 2]);
    } finally { ws.dispose(); }
  });
  it("keeps an unfinished block as a named refusal, not a silent change", () => {
    const { ir, paths } = blocksToIr({ blocks: { blocks: [{ type: "ir_model", id: "model-root", extraState: { version: 2 },
      inputs: { RULES: { block: { type: "ir_rule", id: "r", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" },
        inputs: { LEFT: { block: { type: "ir_const", id: "k", fields: { VALUE: "3" } } } } } } } }] } });
    expect((ir.constraints as Record<string, unknown>[])[0].right).toEqual({ const: null });
    expect(paths.get("k")).toEqual(["constraints", 0, "left"]);
    expect(paths.get("r")).toEqual(["constraints", 0]);
  });

  it("counts blocks left outside the model (Review Focus 1)", () => {
    const { outside } = blocksToIr({ blocks: { blocks: [
      { type: "ir_model", id: "model-root", extraState: { version: 2 } },
      { type: "ir_rule", id: "stray", fields: { ID: "c", NOTE: "", SEVERITY: "hard", WEIGHT: "1", RELATION: "<=" } },
    ] } });
    expect(outside).toBe(1);
  });
});
