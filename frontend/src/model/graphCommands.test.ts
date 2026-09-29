import { describe, expect, it } from "vitest";
import { checkIrShape } from "../ir/validate";
import { applyDeletion, connect, connectionFor, planDeletion, rename } from "./graphCommands";
import type { FormDraft } from "./draftIr";
import { publishable, withFormDraft, EMPTY_MODEL } from "./draftIr";

/** Nurses and shifts: `assign` decides who works which shift; `cost` and `demand` are data. */
function draft(): FormDraft {
  return {
    sets: ["nurse", "shift"],
    parameters: { cost: { index: ["nurse", "shift"] }, demand: { index: ["shift"] } },
    variables: {
      assign: { domain: "binary", index: ["nurse", "shift"] },
      overtime: { domain: "continuous", index: ["nurse"], lower: 0, upper: 10 },
      spare: { domain: "integer", index: [], lower: 0, upper: 5 },
    },
    constraints: [
      { id: "cover", forall: [{ index: "s", set: "shift" }], severity: "hard", relation: ">=",
        left: { add: [{ sum: { var: "assign", index: ["n", "s"] }, over: [{ index: "n", set: "nurse" }] }, { var: "spare", index: [] }] },
        right: { par: "demand", index: ["s"] } },
      { id: "hours", forall: [{ index: "n", set: "nurse" }], severity: "hard", relation: "<=",
        left: { var: "overtime", index: ["n"] }, right: { const: 8 } },
      { id: "only_spare", severity: "hard", relation: "<=", left: { var: "spare", index: [] }, right: { const: 3 } },
    ],
    objective: { sense: "minimize", mode: "weighted", terms: [
      { id: "pay", weight: 1, expression: { sum: { mul: [{ par: "cost", index: ["n", "s"] }, { var: "assign", index: ["n", "s"] }] },
        over: [{ index: "n", set: "nurse" }, { index: "s", set: "shift" }] } },
      { id: "extra", weight: 2, expression: { sum: { var: "overtime", index: ["n"] }, over: [{ index: "n", set: "nurse" }] } },
    ] },
  };
}

/** What Publish would send, checked by the same validator the server mirrors: null when valid. */
const refusal = (d: FormDraft) => checkIrShape(publishable(withFormDraft({ ...EMPTY_MODEL }, d)));

describe("what connecting two cards means", () => {
  it("gives one meaning per pair of kinds, and says why a pair has none", () => {
    expect(connectionFor({ part: "sets", name: "nurse" }, { part: "variables", name: "x" })).toMatchObject({ kind: "index" });
    expect(connectionFor({ part: "sets", name: "nurse" }, { part: "rules", name: "r" })).toMatchObject({ kind: "for-each" });
    expect(connectionFor({ part: "variables", name: "x" }, { part: "rules", name: "r" })).toMatchObject({ kind: "use-in-rule" });
    expect(connectionFor({ part: "parameters", name: "p" }, { part: "rules", name: "r" })).toMatchObject({ kind: "use-in-rule" });
    expect(connectionFor({ part: "variables", name: "x" }, { part: "objective", name: "goal" })).toMatchObject({ kind: "use-in-objective" });
    expect(connectionFor({ part: "parameters", name: "p" }, { part: "objective", name: "goal" })).toMatchObject({ refused: expect.stringContaining("is data") });
    expect(connectionFor({ part: "rules", name: "r" }, { part: "variables", name: "x" })).toHaveProperty("refused");
    expect(connectionFor({ part: "variables", name: "x" }, { part: "sets", name: "s" })).toHaveProperty("refused");
  });
});

describe("connecting", () => {
  it("counts a decision in a rule, bound to the rule's own for-each and summed over the rest", () => {
    const next = connect(draft(), { kind: "use-in-rule", source: { part: "variables", name: "assign" }, rule: "hours", coefficient: 2 });
    const hours = next.constraints.find((r) => r.id === "hours")!;
    expect(hours.left).toEqual({ add: [
      { var: "overtime", index: ["n"] },
      { sum: { mul: [{ const: 2 }, { var: "assign", index: ["n", "s"] }] }, over: [{ index: "s", set: "shift" }] },
    ] });
    expect(refusal(next)).toBeNull();
  });

  it("adds a parameter to a rule's limit", () => {
    const next = connect(draft(), { kind: "use-in-rule", source: { part: "parameters", name: "demand" }, rule: "only_spare", coefficient: 1 });
    expect(next.constraints.find((r) => r.id === "only_spare")!.right).toEqual({ add: [{ const: 3 },
      { sum: { par: "demand", index: ["s"] }, over: [{ index: "s", set: "shift" }] }] });
    expect(refusal(next)).toBeNull();
  });

  it("adds a goal term for a decision, summed over its sets, with a fresh id", () => {
    const next = connect(draft(), { kind: "use-in-objective", variable: "overtime", coefficient: 1 });
    expect(next.objective.terms.at(-1)).toEqual({ id: "overtime_term", weight: 1,
      expression: { sum: { var: "overtime", index: ["n"] }, over: [{ index: "n", set: "nurse" }] } });
    expect(refusal(next)).toBeNull();
  });

  it("makes a rule hold for each member of a set, with an index not already taken", () => {
    const next = connect(draft(), { kind: "for-each", set: "nurse", rule: "cover" });
    expect(next.constraints[0].forall).toEqual([{ index: "s", set: "shift" }, { index: "n_2", set: "nurse" }]);
  });

  it("indexes an unused decision, and refuses one in use, naming the uses", () => {
    const unused = { ...draft(), variables: { ...draft().variables, bonus: { domain: "continuous" as const, index: [] } } };
    expect(connect(unused, { kind: "index", set: "shift", variable: "bonus" }).variables.bonus.index).toEqual(["shift"]);
    expect(() => connect(draft(), { kind: "index", set: "shift", variable: "overtime" })).toThrow("overtime is used by hours, extra");
  });

  it("never changes a draft in place", () => {
    const before = draft();
    const copy = JSON.parse(JSON.stringify(before));
    connect(before, { kind: "use-in-objective", variable: "spare", coefficient: 3 });
    expect(before).toEqual(copy);
  });
});

describe("deleting", () => {
  it("lists what goes and what is trimmed before doing anything", () => {
    expect(planDeletion(draft(), { part: "variables", name: "spare" })).toEqual({
      target: { part: "variables", name: "spare" }, removes: ["only_spare"], trims: ["cover"],
    });
  });

  it("removes the decision and exactly those uses: every unrelated rule and term is left as it was", () => {
    const before = draft();
    const next = applyDeletion(before, { part: "variables", name: "spare" });
    expect(next.variables.spare).toBeUndefined();
    expect(next.constraints.map((r) => r.id)).toEqual(["cover", "hours"]);
    expect(next.constraints[0].left).toEqual({ sum: { var: "assign", index: ["n", "s"] }, over: [{ index: "n", set: "nurse" }] });
    expect(next.constraints[1]).toEqual(before.constraints[1]);
    expect(next.objective.terms).toEqual(before.objective.terms);
    expect(next.parameters).toEqual(before.parameters);
    expect(refusal(next)).toBeNull();
  });

  it("a goal term with no decision left goes; one that still reads a decision is trimmed", () => {
    const next = applyDeletion(draft(), { part: "parameters", name: "cost" });
    expect(next.objective.terms.map((t) => t.id)).toEqual(["extra"]);
    expect(next.parameters.cost).toBeUndefined();
  });

  it("refuses to delete a set something is indexed by, and says what", () => {
    expect(planDeletion(draft(), { part: "sets", name: "shift" }).refused).toBe("assign, cost, demand are indexed by shift; delete or re-index them first.");
  });

  it("deletes one rule and nothing else", () => {
    const before = draft();
    const next = applyDeletion(before, { part: "rules", name: "hours" });
    expect(next.constraints).toEqual([before.constraints[0], before.constraints[2]]);
    expect(next.variables).toEqual(before.variables);
  });
});

describe("renaming", () => {
  it("renames a decision and every reference to it", () => {
    const next = rename(draft(), { part: "variables", name: "assign" }, "works");
    expect(next.variables.works).toBeDefined();
    expect(next.variables.assign).toBeUndefined();
    expect(JSON.stringify(next)).not.toContain('"assign"');
    expect(refusal(next)).toBeNull();
  });

  it("leaves the names that belong to the domain's data -- sets and parameters -- to the domain's pages", () => {
    expect(() => rename(draft(), { part: "parameters", name: "demand" }, "need")).toThrow("Parameters page");
    expect(() => rename(draft(), { part: "sets", name: "shift" }, "slot")).toThrow("Record types page");
  });

  it("refuses a taken name and an invalid one", () => {
    expect(() => rename(draft(), { part: "variables", name: "spare" }, "overtime")).toThrow("already");
    expect(() => rename(draft(), { part: "variables", name: "spare" }, "Spare Nurses")).toThrow("lower-case");
    expect(() => rename(draft(), { part: "rules", name: "hours" }, "cover")).toThrow("already a rule");
  });
});
