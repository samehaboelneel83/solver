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
    expect(RULE_SHAPES.map((s) => s.needs(empty))).toEqual(["a decision", "a decision over a set", "a decision over two sets"]);
    expect(RULE_SHAPES.every((s) => s.needs(CONTEXT) === null)).toBe(true);
  });
});
