import { describe, expect, it } from "vitest";
import { checkIrShape } from "./validate";

/** A place rule as the platform's layout tool writes it (plan phase 1C): the same checks as app/ir/validate.py. */
const IR = {"version": 2, "sets": ["slot", "area"], "parameters": {}, "variables": {"placed": {"index": ["slot"], "domain": "binary"}, "x": {"index": ["slot"], "domain": "integer", "lower": 0, "upper": 8}, "y": {"index": ["slot"], "domain": "integer", "lower": 0, "upper": 4}, "turned": {"index": ["slot"], "domain": "binary"}, "aisle_side": {"index": ["slot"], "domain": "integer", "lower": 0, "upper": 3}}, "constraints": [{"id": "c_layout", "severity": "hard", "note": "Items on the free area, no two on one cell, each aisle free", "place": {"slots": {"index": "s", "set": "slot"}, "chosen": {"var": "placed", "index": ["s"]}, "x": {"var": "x", "index": ["s"]}, "y": {"var": "y", "index": ["s"]}, "length": "length_cells", "width": "width_cells", "areas": {"index": "a", "set": "area"}, "shape": "shape", "step": 0.5, "origin": [0.0, 0.0], "turn": {"var": "turned", "index": ["s"]}, "can_turn": "can_turn", "side": {"var": "aisle_side", "index": ["s"]}, "aisle": 1, "aisle_sides": "long"}}], "objective": {"sense": "maximize", "terms": [{"id": "o_items", "weight": 1, "expression": {"sum": {"var": "placed", "index": ["s"]}, "over": [{"index": "s", "set": "slot"}]}}]}};

const withPlace = (change: Record<string, unknown>) => ({
  ...IR,
  constraints: [{ ...IR.constraints[0], place: { ...IR.constraints[0].place, ...change } }],
});

describe("place rule", () => {
  it("accepts the layout tool's plan", () => {
    expect(checkIrShape(IR)).toBeNull();
  });

  it("refuses a bad grid, a soft one and a decision of the wrong kind", () => {
    expect(checkIrShape(withPlace({ step: 0 }))?.code).toBe("place_malformed");
    expect(checkIrShape(withPlace({ unknown: 1 }))?.code).toBe("place_malformed");
    expect(checkIrShape({ ...IR, constraints: [{ ...IR.constraints[0], severity: "soft", weight: 1 }] })?.code).toBe("place_on_soft");
    expect(checkIrShape({ ...IR, variables: { ...IR.variables, placed: { index: ["slot"], domain: "integer" } } })?.code).toBe("place_domain");
  });

  it("takes access features, named with their shape field, and refuses one without the other", () => {
    const sets = [...IR.sets, "access_point"];
    expect(checkIrShape({ ...withPlace({ access: { index: "e", set: "access_point" }, access_shape: "shape" }), sets })).toBeNull();
    expect(checkIrShape({ ...withPlace({ access: { index: "e", set: "access_point" } }), sets })?.code).toBe("place_malformed");
  });
});
