import { describe, expect, it } from "vitest";
import { applyGuidedCommand, type GuidedCommand } from "./guidedCommands";
import { formDraftOf, publishable, withFormDraft } from "./draftIr";
import { checkIrShape } from "../ir";

const original = { version: 2, sets: ["employee", "day"], parameters: {},
  variables: { assign: { domain: "binary", index: ["employee", "day"] } }, constraints: [],
  objective: { sense: "minimize", terms: [] } };
const rule: GuidedCommand = { kind: "rule", name: "daily_limit", decision: "assign", separate: [1], relation: "<=", limit: "2", preference: false, penalty: "", note: "Daily staffing limit" };

describe("guided creation commands", () => {
  it("multiplies before summing and preserves the parameter's declared index order", () => {
    const draft = formDraftOf({ ...original, parameters: { cost: { index: ["day", "employee"] } } });
    const next = applyGuidedCommand(draft, { kind: "objective", name: "cost_total", decision: "assign", sense: "minimize", weight: "1", coefficient: { name: "cost", dimensions: [1, 0] } }, original.sets);
    expect(next.objective.terms[0].expression).toEqual({ sum: { mul: [{ par: "cost", index: ["i2", "i1"] }, { var: "assign", index: ["i1", "i2"] }] }, over: [{ index: "i1", set: "employee" }, { index: "i2", set: "day" }] });
    expect(checkIrShape(publishable(withFormDraft(original, next)))).toBeNull();
  });
  it("uses capacity per day on the right while summing employees on the left", () => {
    const draft = formDraftOf({ ...original, parameters: { capacity: { index: ["day"] }, hours: { index: ["employee"] } } });
    const next = applyGuidedCommand(draft, { ...rule, limit: "", limitParameter: { name: "capacity", dimensions: [1] }, coefficient: { name: "hours", dimensions: [0] } }, original.sets);
    expect(next.constraints[0].right).toEqual({ par: "capacity", index: ["i2"] });
    expect(checkIrShape(publishable(withFormDraft(original, next)))).toBeNull();
    expect(() => applyGuidedCommand(draft, { ...rule, separate: [], limitParameter: { name: "capacity", dimensions: [1] } }, original.sets)).toThrow("kept separate");
  });
  it("rejects stale, entity-valued and incorrectly ordered parameter mappings", () => {
    const draft = formDraftOf({ ...original, parameters: { cost: { index: ["day", "employee"] }, manager: { index: ["day"], entity: "employee" } } });
    for (const coefficient of [{ name: "missing", dimensions: [] }, { name: "manager", dimensions: [1] }, { name: "cost", dimensions: [0, 1] }, { name: "cost", dimensions: [-1, 0] }]) {
      expect(() => applyGuidedCommand(draft, { ...rule, coefficient }, original.sets)).toThrow();
    }
  });
  it("supports scalar numeric parameters without inventing an index", () => {
    const draft = formDraftOf({ ...original, parameters: { capacity: { index: [] } } });
    expect(applyGuidedCommand(draft, { ...rule, separate: [], limitParameter: { name: "capacity", dimensions: [] } }, original.sets).constraints[0].right).toEqual({ par: "capacity", index: [] });
  });
  it("limits the sum over employees separately for each day", () => {
    const next = applyGuidedCommand(formDraftOf(original), rule, original.sets);
    expect(next.constraints[0]).toEqual({ id: "daily_limit", note: "Daily staffing limit", forall: [{ index: "i2", set: "day" }], left: { sum: { var: "assign", index: ["i1", "i2"] }, over: [{ index: "i1", set: "employee" }] }, relation: "<=", right: { const: 2 }, severity: "hard" });
    expect(next.constraints[0]).not.toHaveProperty("weight");
    expect(original.constraints).toHaveLength(0);
  });
  it("validates a complete generated variable/rule/objective model against the actual IR contract", () => {
    let next = formDraftOf(original);
    next = applyGuidedCommand(next, { kind: "variable", name: "staff", domain: "integer", index: ["day"], lower: "0", upper: "20" }, original.sets);
    next = applyGuidedCommand(next, rule, original.sets);
    next = applyGuidedCommand(next, { kind: "objective", name: "staff_total", decision: "staff", sense: "minimize", weight: "2" }, original.sets);
    expect(checkIrShape(publishable(withFormDraft(original, next)))).toBeNull();
  });
  it("keeps independent indices when a variable uses a set twice", () => {
    const draft = formDraftOf({ ...original, variables: { flow: { domain: "continuous", index: ["day", "day"] } } });
    const next = applyGuidedCommand(draft, { ...rule, decision: "flow", separate: [0] }, original.sets);
    expect(next.constraints[0].forall).toEqual([{ index: "i1", set: "day" }]);
    expect(next.constraints[0].left).toEqual({ sum: { var: "flow", index: ["i1", "i2"] }, over: [{ index: "i2", set: "day" }] });
  });
  it("preserves existing advanced rules and refuses duplicate ids", () => {
    const draft = formDraftOf(original);
    draft.constraints.push({ id: "advanced", connected: { custom: true } } as never);
    const next = applyGuidedCommand(draft, rule, original.sets);
    expect(next.constraints[0]).toEqual(draft.constraints[0]);
    expect(() => applyGuidedCommand(next, rule, original.sets)).toThrow("already");
  });
  it.each(["", "NaN", "Infinity"])("rejects an invalid numeric limit %s", limit => {
    expect(() => applyGuidedCommand(formDraftOf(original), { ...rule, limit }, original.sets)).toThrow("Limit must be a number");
  });
  it("requires integer penalties and objective weights", () => {
    expect(() => applyGuidedCommand(formDraftOf(original), { ...rule, preference: true, penalty: "1.5" }, original.sets)).toThrow("positive whole number");
    expect(() => applyGuidedCommand(formDraftOf(original), { kind: "objective", name: "total", decision: "assign", sense: "minimize", weight: "1.5" }, original.sets)).toThrow("positive whole number");
  });
  it("does not silently change an existing objective direction or combination mode", () => {
    const draft = formDraftOf(original);
    draft.objective = { sense: "maximize", mode: "lex", terms: [{ id: "first", weight: 1, expression: { const: 2 } }] };
    const command: GuidedCommand = { kind: "objective", name: "second", decision: "assign", sense: "minimize", weight: "1" };
    expect(() => applyGuidedCommand(draft, command, original.sets)).toThrow("direction changed");
    expect(applyGuidedCommand(draft, { ...command, sense: "maximize" }, original.sets).objective.mode).toBe("lex");
  });
  it("rejects stale declarations and invalid bounds", () => {
    expect(() => applyGuidedCommand(formDraftOf(original), { ...rule, decision: "removed" }, original.sets)).toThrow("existing");
    expect(() => applyGuidedCommand(formDraftOf(original), { kind: "variable", name: "count", domain: "integer", index: [], lower: "2", upper: "1" }, [])).toThrow("Minimum");
  });
});
