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
