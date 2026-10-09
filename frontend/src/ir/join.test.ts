import { describe, expect, it } from "vitest";
import { checkIrShape } from "./validate";

/** A join rule (network design) as tests/test_join.py writes it: the same refusals, at the same locs, as app/ir/validate.py. */
const IR = {"version": 2, "sets": ["site", "segment"], "relationships": ["seg_a", "seg_b"], "parameters": {"cost": {"index": ["segment"]}, "prize": {"index": ["site"]}, "required": {"index": ["site"]}, "forced": {"index": ["segment"]}, "banned": {"index": ["segment"]}}, "variables": {"lay": {"index": ["segment"], "domain": "binary"}, "serve": {"index": ["site"], "domain": "binary"}}, "constraints": [{"id": "c_join", "severity": "hard", "join": {"links": {"index": "l", "set": "segment"}, "build": {"var": "lay", "index": ["l"]}, "ends": ["seg_a", "seg_b"], "places": {"index": "p", "set": "site"}, "sources": "exchange", "use": {"var": "serve", "index": ["p"]}}}, {"id": "c_required", "severity": "hard", "forall": [{"index": "p", "set": "site"}], "left": {"var": "serve", "index": ["p"]}, "relation": ">=", "right": {"par": "required", "index": ["p"]}}, {"id": "c_forced", "severity": "hard", "forall": [{"index": "l", "set": "segment"}], "left": {"var": "lay", "index": ["l"]}, "relation": ">=", "right": {"par": "forced", "index": ["l"]}}, {"id": "c_banned", "severity": "hard", "forall": [{"index": "l", "set": "segment"}], "left": {"mul": [{"par": "banned", "index": ["l"]}, {"var": "lay", "index": ["l"]}]}, "relation": "<=", "right": {"const": 0}}], "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {"sum": {"mul": [{"par": "cost", "index": ["l"]}, {"var": "lay", "index": ["l"]}]}, "over": [{"index": "l", "set": "segment"}]}}, {"id": "o_prize", "weight": -1, "expression": {"sum": {"mul": [{"par": "prize", "index": ["p"]}, {"var": "serve", "index": ["p"]}]}, "over": [{"index": "p", "set": "site"}]}}]}};

type Json = Record<string, unknown>;
const body = (IR.constraints[0] as Json).join as Json;
const withJoin = (change: Json) => ({
  ...IR, constraints: [{ ...IR.constraints[0], join: { ...body, ...change } }, ...IR.constraints.slice(1)],
});

describe("join rule", () => {
  it("is accepted as written", () => {
    expect(checkIrShape(IR)).toBeNull();
  });
  it("refuses what the server refuses", () => {
    expect(checkIrShape(withJoin({ ends: "seg_a" }))?.code).toBe("join_malformed");
    expect(checkIrShape(withJoin({ ends: ["seg_a", "nope"] }))?.loc).toEqual(["constraints", 0, "join", "ends", 1]);
    expect(checkIrShape(withJoin({ ends: ["seg_a", "nope"] }))?.code).toBe("join_ends_invalid");
    expect(checkIrShape(withJoin({ build: { var: "lay", index: ["p"] } }))?.code).toBe("join_index_mismatch");
    expect(checkIrShape(withJoin({ extra: 1 }))?.code).toBe("join_malformed");
    expect(checkIrShape(withJoin({ sources: 3 }))?.code).toBe("join_malformed");
    const { places: _dropped, ...noPlaces } = body;
    expect(checkIrShape({ ...IR, constraints: [{ ...IR.constraints[0], join: noPlaces }, ...IR.constraints.slice(1)] })?.loc)
      .toEqual(["constraints", 0, "join", "places"]);
    expect(checkIrShape({ ...IR, constraints: [{ ...IR.constraints[0], severity: "soft", weight: 3 }, ...IR.constraints.slice(1)] })?.code)
      .toBe("join_on_soft");
    expect(checkIrShape({ ...IR, variables: { ...IR.variables, serve: { index: ["site"], domain: "integer" } } })?.code)
      .toBe("join_not_binary");
    expect(checkIrShape({ ...IR, constraints: [{ ...IR.constraints[0], chance: { epsilon: 0.1 } }, ...IR.constraints.slice(1)] })?.code)
      .toBe("chance_misplaced");
  });

  it("asks a demand for sources, and capacity, supply and carry for a demand", () => {
    expect(checkIrShape(withJoin({ demand: "need" }))).toBeNull();
    const { sources: _s, ...unsourced } = body;
    const noSources = { ...IR, constraints: [{ ...IR.constraints[0], join: { ...unsourced, demand: "need" } }, ...IR.constraints.slice(1)] };
    expect(checkIrShape(noSources)?.loc).toEqual(["constraints", 0, "join", "demand"]);
    expect(checkIrShape(withJoin({ capacity: "cap" }))?.code).toBe("join_malformed");
    expect(checkIrShape(withJoin({ demand: 3 }))?.code).toBe("join_malformed");
    expect(checkIrShape(withJoin({ demand: "need", carry: { var: "lay", index: ["l"] } }))?.code).toBe("join_carry_invalid");
    expect(checkIrShape(withJoin({ demand: "need", carry: { var: "lay", index: ["p"] } }))?.code).toBe("join_index_mismatch");
    expect(checkIrShape(withJoin({ demand: "need", capacity: "cap", supply: "supply" }))).toBeNull();
  });
});
