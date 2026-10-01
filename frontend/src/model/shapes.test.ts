import { describe, expect, it } from "vitest";
import { checkGoal, checkRule } from "./blockCheck";
import { goalFromShape, GOAL_SHAPES, ruleFromShape, RULE_SHAPES } from "./shapes";
import type { ModelContext } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["employee", "day"],
  setIds: {},
  attributes: {},
  variables: { assign: { index: ["employee", "day"], domain: "binary" } },
  parameters: { demand: { index: ["day"] }, cost: { index: ["employee", "day"] } },
  relationships: [],
};

describe("starting shapes", () => {
  it("builds each rule shape from the model's own names, and every one checks out", () => {
    expect(ruleFromShape("cover_each", "c_1", CONTEXT)).toEqual({
      id: "c_1",
      forall: [{ index: "d", set: "day" }],
      left: { sum: { var: "assign", index: ["e", "d"] }, over: [{ index: "e", set: "employee" }] },
      relation: ">=",
      right: { par: "demand", index: ["d"] },
      severity: "hard",
    });
    for (const { shape } of RULE_SHAPES) {
      expect(checkRule(ruleFromShape(shape, "c_x", CONTEXT), CONTEXT), shape).toEqual([]);
    }
  });

  it("reads the model's data where a shape has a limit to compare with", () => {
    const each = ruleFromShape("cap_each", "c_2", CONTEXT);
    expect(each.right).toEqual({ par: "cost", index: [each.forall![0].index, each.forall![1].index] });
  });

  it("builds a goal that counts or costs a decision", () => {
    const cost = goalFromShape("cost", "o_1", CONTEXT);
    expect(cost.expression).toMatchObject({ sum: { mul: [{ par: "cost" }, { var: "assign" }] } });
    for (const { shape } of GOAL_SHAPES) expect(checkGoal(goalFromShape(shape, "o_x", CONTEXT).expression!, CONTEXT)).toEqual([]);
  });

  it("offers a shape only when the model has what it needs, and says what", () => {
    const empty: ModelContext = { ...CONTEXT, variables: {} };
    expect(RULE_SHAPES.map((s) => s.needs(empty))).toEqual(["a decision", "a decision over a set", "a decision over two sets",
      "a decision over a set that a relationship reaches",
      "a yes/no decision over a set, and another decision over that set and more",
      "a decision, and 0/1 reach data -- tick it under “Data this model reads” -- or a relationship to the items it covers",
      "a decision over two sets",
      "a yes/no decision over who and when, and a too-close link between slots (Data values → From times)"]);
    // A model with no relationships has no walk to offer, no yes/no over one set, no reach data.
    expect(RULE_SHAPES.filter((s) => s.needs(CONTEXT) !== null).map((s) => s.shape))
      .toEqual(["cap_linked", "cap_when_chosen", "cover_within_reach", "rest_between"]);
  });
});

describe("a rule shape with a walk", () => {
  const ORG: ModelContext = {
    sets: ["employee", "unit"],
    setIds: {},
    attributes: {},
    variables: { pick: { index: ["employee"], domain: "binary" } },
    parameters: {},
    relationships: [{ name: "manages", from: "employee", to: "employee" }],
  };

  it("walks a hierarchy down from each item to everything under it", () => {
    expect(RULE_SHAPES.find((s) => s.shape === "cap_linked")!.needs(ORG)).toBeNull();
    const rule = ruleFromShape("cap_linked", "c_1", ORG);
    expect(rule).toEqual({
      id: "c_1",
      forall: [{ index: "e", set: "employee" }],
      left: { sum: { var: "pick", index: ["e2"] }, over: [{ index: "e2", set: "employee", via: { rel: "manages", from: "e", depth: "any" } }] },
      relation: "<=",
      right: { const: 1 },
      severity: "hard",
    });
    expect(checkRule(rule, ORG)).toEqual([]);
  });

  it("walks back from each unit to the people in it, one step", () => {
    const rule = ruleFromShape("cap_linked", "c_2", { ...ORG, relationships: [{ name: "belongs_to", from: "employee", to: "unit" }] });
    expect(rule.forall).toEqual([{ index: "u", set: "unit" }]);
    expect(rule.left).toEqual({ sum: { var: "pick", index: ["e"] }, over: [{ index: "e", set: "employee", via: { rel: "belongs_to", to: "u" } }] });
  });

  it("prefers a hierarchy when there is one", () => {
    const both = { ...ORG, relationships: [{ name: "belongs_to", from: "employee", to: "unit" }, { name: "manages", from: "employee", to: "employee", hierarchy: true }] };
    expect((ruleFromShape("cap_linked", "c_3", both).left as { over: { via: { rel: string } }[] }).over[0].via.rel).toBe("manages");
  });

  it("is not offered without a relationship", () => {
    expect(RULE_SHAPES.find((s) => s.shape === "cap_linked")!.needs({ ...ORG, relationships: [] })).toBe("a decision over a set that a relationship reaches");
  });
});

describe("placing and covering (improvement plan 4.3)", () => {
  const PLACE: ModelContext = {
    sets: ["yard", "truck", "hotspot"],
    setIds: {},
    attributes: { yard: [{ name: "max_trucks", data_type: "integer" }] },
    variables: {
      open: { index: ["yard"], domain: "binary" },
      station: { index: ["yard", "truck"], domain: "binary" },
    },
    parameters: { reach: { index: ["yard", "hotspot"] } },
    relationships: [],
  };

  it("holds each site to its capacity, and to nothing when it is not chosen", () => {
    const rule = ruleFromShape("cap_when_chosen", "c_cap", PLACE);
    expect(rule).toMatchObject({
      forall: [{ set: "yard" }],
      left: { sum: { var: "station" }, over: [{ set: "truck" }] },
      relation: "<=",
      right: { mul: [{ attr: { name: "max_trucks" } }, { var: "open" }] },
    });
    expect(checkRule(rule, PLACE)).toEqual([]);
  });

  it("asks each item to be covered from within its reach", () => {
    const rule = ruleFromShape("cover_within_reach", "c_cover", { ...PLACE, variables: { station: PLACE.variables.station } });
    expect(rule).toMatchObject({
      forall: [{ set: "hotspot" }],
      left: { sum: { mul: [{ par: "reach" }, { var: "station" }] } },
      relation: ">=",
      right: { const: 1 },
    });
    expect(checkRule(rule, PLACE)).toEqual([]);
  });

  it("reads the 0/1 reach data, not travel minutes declared before it (user test, Alexandria)", () => {
    const both: ModelContext = { ...PLACE, variables: { open: PLACE.variables.open },
      parameters: { drive_min: { index: ["yard", "hotspot"] }, reach: { index: ["yard", "hotspot"] } } };
    const rule = ruleFromShape("cover_within_reach", "c_cover", both);
    expect(rule.left).toMatchObject({ sum: { mul: [{ par: "reach" }, { var: "open" }] } });
  });

  it("finds the decision over two sets even when a yes/no over one set came first", () => {
    expect(RULE_SHAPES.find((s) => s.shape === "total_per_item")!.needs(PLACE)).toBeNull();
    const rule = ruleFromShape("total_per_item", "c_each", PLACE);
    expect(rule).toMatchObject({ forall: [{ set: "yard" }], left: { sum: { var: "station" }, over: [{ set: "truck" }] } });
    expect(checkRule(rule, PLACE)).toEqual([]);
  });

  it("walks a relationship when reach is links, not data", () => {
    const linked: ModelContext = { ...PLACE, parameters: {}, variables: { open: PLACE.variables.open },
      relationships: [{ name: "within_reach", from: "yard", to: "hotspot" }] };
    const rule = ruleFromShape("cover_within_reach", "c_cover", linked);
    expect(rule.left).toMatchObject({ sum: { var: "open" }, over: [{ set: "yard", via: { rel: "within_reach" } }] });
    expect(checkRule(rule, linked)).toEqual([]);
  });
});

describe("workforce rules (improvement plan 5.2)", () => {
  const ROSTER: ModelContext = {
    sets: ["operator", "time_block"],
    setIds: {},
    attributes: { operator: [{ name: "max_shifts", data_type: "integer" }] },
    variables: { work: { index: ["operator", "time_block"], domain: "binary" } },
    parameters: {},
    relationships: [{ name: "too_close", from: "time_block", to: "time_block" }],
  };

  it("caps each person's total at their own limit", () => {
    const rule = ruleFromShape("total_per_item", "c_max", ROSTER);
    expect(rule).toMatchObject({ forall: [{ set: "operator" }], left: { sum: { var: "work" }, over: [{ set: "time_block" }] },
      relation: "<=", right: { attr: { name: "max_shifts" } } });
    expect(checkRule(rule, ROSTER)).toEqual([]);
  });

  it("keeps rest between shifts: never both ends of a too-close link", () => {
    const rule = ruleFromShape("rest_between", "c_rest", ROSTER);
    expect(rule.forall).toHaveLength(3);
    expect(rule.forall![2]).toMatchObject({ set: "time_block", via: { rel: "too_close", from: rule.forall![1].index } });
    expect(rule).toMatchObject({ left: { add: [{ var: "work" }, { var: "work" }] }, relation: "<=", right: { const: 1 } });
    expect(checkRule(rule, ROSTER)).toEqual([]);
  });
});
