import { describe, expect, it } from "vitest";
import { checkIrShape } from "../ir/validate";
import { EMPTY_MODEL, publishable, withFormDraft, type FormDraft } from "./draftIr";
import { applyPattern, PATTERNS, tasksOf } from "./patterns";

const SETS = ["job", "machine", "vehicle", "stop", "cell", "zone"];
const empty = (): FormDraft => ({ sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } });
const refusal = (d: FormDraft) => checkIrShape(publishable(withFormDraft({ ...EMPTY_MODEL }, d)));

function withTask(optional = false): FormDraft {
  const d = { ...empty(), parameters: { length: { index: ["job", "machine"] }, cap: { index: ["machine"] }, need: { index: ["job", "machine"] } } };
  return applyPattern(d, { kind: "task", name: "op", index: ["job", "machine"], size: { parameter: "length" }, horizon: 100, optional }, SETS);
}

describe("the pattern catalogue", () => {
  it("offers scheduling and routing patterns", () => {
    expect(PATTERNS.map((p) => p.kind)).toEqual(["task", "one_at_a_time", "shared_capacity", "routes", "regions"]);
  });
});

describe("a task with a duration", () => {
  it("declares a start, an end and the task, whole, with the sets it needs", () => {
    const d = withTask(true);
    expect(d.sets).toEqual(["job", "machine"]);
    expect(d.variables.op).toEqual({ index: ["job", "machine"], domain: "interval", start: "op_start", end: "op_end", size: "length", presence: "op_done" });
    expect(d.variables.op_start).toEqual({ index: ["job", "machine"], domain: "integer", lower: 0, upper: 100 });
    expect(d.variables.op_done.domain).toBe("binary");
    expect(tasksOf(d)).toEqual([{ name: "op", index: ["job", "machine"] }]);
    expect(refusal(d)).toBeNull();
  });

  it("refuses a duration parameter of the wrong shape, and a fractional duration", () => {
    expect(() => applyPattern({ ...empty(), parameters: { cap: { index: ["machine"] } } },
      { kind: "task", name: "op", index: ["job"], size: { parameter: "cap" }, horizon: 10, optional: false }, SETS)).toThrow("one number for each job");
    expect(() => applyPattern(empty(), { kind: "task", name: "op", index: [], size: { const: 1.5 }, horizon: 10, optional: false }, SETS))
      .toThrow("whole number");
  });
});

describe("one at a time and shared capacity", () => {
  it("a machine does one job at a time: for each machine, the jobs' tasks do not overlap", () => {
    const d = applyPattern(withTask(), { kind: "one_at_a_time", name: "one_job", task: "op", resource: [1] }, SETS);
    expect(d.constraints.at(-1)).toEqual({ id: "one_job", severity: "hard", forall: [{ index: "m", set: "machine" }],
      no_overlap: { interval: { var: "op", index: ["j", "m"] }, over: [{ index: "j", set: "job" }] } });
    expect(refusal(d)).toBeNull();
  });

  it("shared capacity reads demand per task and capacity per resource", () => {
    const d = applyPattern(withTask(), { kind: "shared_capacity", name: "fits", task: "op", resource: [1],
      demand: { parameter: "need" }, capacity: { parameter: "cap" } }, SETS);
    expect(d.constraints.at(-1)?.cumulative).toEqual({ interval: { var: "op", index: ["j", "m"] }, over: [{ index: "j", set: "job" }],
      demand: { par: "need", index: ["j", "m"] }, capacity: { par: "cap", index: ["m"] } });
    expect(refusal(d)).toBeNull();
  });

  it("refuses a capacity indexed by the wrong sets, and a resource that leaves no tasks", () => {
    expect(() => applyPattern(withTask(), { kind: "shared_capacity", name: "fits", task: "op", resource: [1],
      demand: { const: 1 }, capacity: { parameter: "need" } }, SETS)).toThrow("capacity parameter must hold one number for each machine");
    expect(() => applyPattern(withTask(), { kind: "one_at_a_time", name: "x", task: "op", resource: [0, 1] }, SETS)).toThrow("at least one dimension");
  });
});

describe("vehicle routes", () => {
  it("declares the visits, the route rule and a travel goal", () => {
    const d = applyPattern({ ...empty(), parameters: { distance: { index: ["stop", "stop"] } } },
      { kind: "routes", name: "tours", vehicles: "vehicle", stops: "stop", depot: "hub", load: { demand: "demand", capacity: "capacity" }, travel: "distance" }, SETS);
    expect(d.variables.tours_visit).toEqual({ index: ["vehicle", "stop", "stop"], domain: "binary" });
    expect(d.constraints[0].route).toMatchObject({ depot: "hub", demand: "demand", capacity: "capacity", visit: { var: "tours_visit" } });
    expect(d.objective.terms[0].id).toBe("tours_travel");
    expect(refusal(d)).toBeNull();
  });

  it("refuses a travel cost that is not per pair of stops", () => {
    expect(() => applyPattern({ ...empty(), parameters: { distance: { index: ["stop"] } } },
      { kind: "routes", name: "tours", vehicles: "vehicle", stops: "stop", depot: "hub", travel: "distance" }, SETS)).toThrow("each pair of stop");
  });
});

describe("connected regions", () => {
  it("declares the assignment, the connected rule and one group per unit", () => {
    const d = applyPattern(empty(), { kind: "regions", name: "zones", units: "cell", groups: "zone", via: "adjacent", everyUnitOnce: true, allowEmpty: false }, SETS);
    expect(d.variables.zones_in).toEqual({ index: ["cell", "zone"], domain: "binary" });
    expect(d.constraints.map((r) => r.id)).toEqual(["zones", "zones_each_once"]);
    expect(d.constraints[1]).toMatchObject({ relation: "=", right: { const: 1 } });
    expect(refusal(d)).toBeNull();
  });
});
