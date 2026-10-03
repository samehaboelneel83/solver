import { describe, expect, it } from "vitest";
import type { Run } from "../api/v1";
import { plain, planWords } from "./planWords";

const base = {
  id: 1, scenario_id: 2, status: "optimal", objective: 43.531746, error: null,
  labels: { feed: { maize: "Maize", soy: "Soybean meal", bran: "Wheat bran" }, employee: { a: "Ahmed", s: "Sara" }, day: { mon: "Monday" } },
  index_sets: { variables: { use: ["feed"], work: ["employee", "day"] }, constraints: {} },
  set_order: { employee: ["a", "s", "o"], day: ["mon", "tue"] },
  assignments: { work: [["a", "mon"], ["s", "mon"]] },
  amounts: { use: [{ index: ["maize"], value: 64.2857 }, { index: ["soy"], value: 29.37 }, { index: ["bran"], value: 0 }] },
  constraints: [
    { constraint_id: "c_batch", hard: true, satisfied: true, penalty_paid: 0 },
    { constraint_id: "c_pref", hard: false, satisfied: false, penalty_paid: 3600 },
  ],
  conflict: null,
} as unknown as Run;

const ir = {
  objective: { sense: "minimize", terms: [{ id: "o_cost" }] },
  variables: { use: { index: ["feed"], domain: "continuous" }, work: { index: ["employee", "day"], domain: "binary" } },
};

describe("a plan in plain words", () => {
  it("says the goal, what was decided and how the rules fared", () => {
    expect(planWords(base, ir)).toEqual({
      headline: "The best plan possible was found.",
      tone: "good",
      lines: [
        "Cost came to 43.53, as low as it can go.",
        "use: Maize 64.29, Soybean meal 29.37.",
        "work: 2 of 6 chosen — Ahmed · Monday, Sara · Monday.",
        "Every required rule holds; 1 preference could not be met, at a cost of 3,600.",
      ],
    });
  });

  it("names the goal by its note, and says 'found' rather than 'can go' when not proven", () => {
    const said = planWords({ ...base, status: "feasible" } as Run,
      { ...ir, objective: { sense: "maximize", terms: [{ id: "o_x", note: "profit" }] } });
    expect(said?.headline).toBe("A plan was found; a better one may exist.");
    expect(said?.lines[0]).toBe("Profit came to 43.53, the highest found.");
  });

  it("leads an infeasible run with the fact, and a failed run with how it ended", () => {
    expect(planWords({ ...base, status: "infeasible", objective: null, conflict: [{ constraint_id: "c", instance: [] }] } as unknown as Run, ir))
      .toEqual({ headline: "No plan can meet every rule.", tone: "bad",
        lines: ["The rules that clash are listed just below: change or relax one of them and solve again."] });
    expect(planWords({ ...base, status: "error" } as Run, ir)?.headline).toBe("No plan was found: the run ended error.");
    expect(planWords({ ...base, status: "running" } as Run, ir)).toBeNull();
  });

  it("says weighted goals as they are combined, not as one total (benchmark round 3)", () => {
    const mixed = { objective: { sense: "maximize", terms: [{ id: "benefit", weight: 1, expression: { var: "pick", index: [] } },
      { id: "cost", weight: -0.2, expression: { var: "pick", index: [] } }] } };
    expect(planWords({ ...base, status: "optimal" } as Run, mixed)?.lines[0])
      .toBe("The goal, benefit less 0.2 × cost, came to 43.53, as high as it can go.");
  });

  it("says what a goal adds up when its name does not (UX audit C-1: 'Morning came to 0')", () => {
    const lectures = { objective: { sense: "minimize", terms: [{ id: "o_morning",
      expression: { sum: { mul: [{ par: "late", index: ["p"] }, { var: "assign", index: ["s", "p"] }] }, over: [] } }] } };
    expect(planWords({ ...base, objective: 0, amounts: {}, assignments: {} } as unknown as Run, lectures)?.lines[0])
      .toBe("Morning, the total of late, came to 0, as low as it can go.");
    const feed = { objective: { sense: "minimize", terms: [{ id: "o_cost", expression: { mul: [{ par: "cost", index: ["f"] }, { var: "use", index: ["f"] }] } }] } };
    expect(planWords(base, feed)?.lines[0]).toBe("Cost came to 43.53, as low as it can go.");
  });

  it("reads names plainly", () => {
    expect(plain("o_total_cost")).toBe("total cost");
    expect(plain("hours_per_week")).toBe("hours per week");
  });

  it("says ordered goals one by one, never as one total (user test, run 746)", () => {
    const run = { ...base, objective: 361,
      params: { objective_mode: "lex", objective_terms: [{ id: "risk_covered", value: 361 }, { id: "yard_rent", value: -255000 }] } } as unknown as Run;
    const said = planWords(run, { ...ir, objective: { sense: "maximize", mode: "lex", terms: [{ id: "risk_covered" }, { id: "yard_rent" }] } } as never);
    expect(said?.lines[0]).toBe("Goals, in order: risk covered 361, then yard rent -255,000 — each as high as it can go given the ones before it.");
  });
});

describe("goals in order, each its own way (benchmark round 5)", () => {
  it("says a goal marked less is better, by its weight, at its own value and low", () => {
    const run = { ...base, params: { objective_mode: "lex", objective_terms: [
      { id: "profit", value: 246100000 }, { id: "water_used", value: 19000000 }] } } as unknown as Run;
    const crops = { objective: { sense: "maximize", mode: "lex", terms: [
      { id: "profit", weight: 1, expression: { sum: { var: "area", index: ["p"] } } },
      { id: "water_used", weight: -1, expression: { sum: { var: "water", index: ["p"] } } },
    ] }, variables: ir.variables };
    expect(planWords(run, crops as never)?.lines[0]).toBe(
      "Goals, in order: profit 246,100,000 as high as it can go, then water used 19,000,000 as low as it can go — each given the ones before it."
    );
  });
});

describe("a cost among maximised goals", () => {
  it("is said as the cost, positive and kept low, not as a negative number (emergency coverage)", () => {
    const run = { ...base, params: { objective_mode: "lex", objective_terms: [
      { id: "o_risk_covered", value: 355 }, { id: "o_running_cost", value: -247000 }] } } as unknown as Run;
    const emergency = { objective: { sense: "maximize", mode: "lex", terms: [
      { id: "o_risk_covered", weight: 1, expression: { sum: { var: "covered", index: ["p"] } } },
      { id: "o_running_cost", weight: 1, expression: { mul: [{ const: -1 }, { sum: { var: "open", index: ["s"] } }] } },
    ] }, variables: ir.variables };
    expect(planWords(run, emergency as never)?.lines[0]).toBe(
      "Goals, in order: risk covered 355 as high as it can go, then running cost 247,000 as low as it can go — each given the ones before it."
    );
  });
});

describe("goals the editor named o_1, o_2", () => {
  it("are said by what they add up, not as “o 1” (user test, Alexandria)", () => {
    const run = { ...base, params: { objective_mode: "lex", objective_terms: [{ id: "o_1", value: 60000 }, { id: "o_2", value: 4 }] } } as unknown as Run;
    const lexIr = {
      objective: { sense: "minimize", mode: "lex", terms: [
        { id: "o_1", expression: { sum: { mul: [{ attr: { of: "y", name: "rent_egp_3_days" } }, { var: "open", index: ["y"] }] } } },
        { id: "o_2", expression: { sum: { var: "base", index: ["y", "t"] } } },
      ] },
      variables: ir.variables,
    };
    expect(planWords(run, lexIr)?.lines[0]).toBe("Goals, in order: rent egp 3 days 60,000, then total base 4 — each as low as it can go given the ones before it.");
  });
});

describe("a goal over many data (benchmark, October 2026)", () => {
  it("names a few and counts the rest, once", () => {
    const reads = ["peak_volume_vph", "capacity_vph", "length_km", "lanes", "speed_kmh"]
      .map((name) => ({ mul: [{ attr: { of: "r", name } }, { var: "x", index: ["r"] }] }));
    const ir = { variables: { x: { index: ["road"], domain: "binary" } },
      objective: { sense: "maximize", terms: [{ id: "o_1", weight: 1, expression: { sum: { add: reads }, over: [{ index: "r", set: "road" }] } }] } };
    const words = planWords({ status: "optimal", objective: 4864.36, constraints: [], assignments: {}, amounts: {} } as unknown as Run, ir)!.lines[0];
    expect(words).toContain("Peak volume vph, capacity vph, length km and 2 more came to 4,864.36");
    expect(words).not.toContain("the total of");
  });
});
