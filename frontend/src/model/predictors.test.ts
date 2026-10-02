import { describe, expect, it } from "vitest";
import { called, declareCalled, offered } from "./predictors";

const WORKSPACE = [{ name: "yield_gb", inputs: ["soil_score", "water_m3", "ndvi"] }, { name: "calls", inputs: ["day"] }];

describe("trained predictors in a model (benchmark, October 2026)", () => {
  it("offers every predictor of the workspace, and keeps what the document declares", () => {
    expect(offered({ old: { inputs: 1 } }, WORKSPACE)).toEqual({ yield_gb: { inputs: 3 }, calls: { inputs: 1 }, old: { inputs: 1 } });
  });

  it("declares exactly the predictors the rules and goals call, with their inputs", () => {
    const goal = { predict: "yield_gb", of: [{ attr: { of: "p", name: "soil" } }, { var: "water", index: ["p"] }, { const: 0.4 }] };
    const ir = { version: 2, constraints: [], objective: { sense: "maximize", terms: [{ id: "o", weight: 1, expression: goal }] } };
    expect([...called(ir.objective)]).toEqual(["yield_gb"]);
    expect(declareCalled(ir, WORKSPACE).predictors).toEqual({ yield_gb: { inputs: 3 } });
    // Nothing called: the document is left as it is.
    const plain = { version: 2, constraints: [], objective: { sense: "minimize", terms: [] } };
    expect(declareCalled(plain, WORKSPACE)).toBe(plain);
  });
});
