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
      "a decision over a set that a relationship reaches"]);
    // A model with no relationships has no walk to offer; everything else is.
    expect(RULE_SHAPES.filter((s) => s.needs(CONTEXT) !== null).map((s) => s.shape)).toEqual(["cap_linked"]);
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
