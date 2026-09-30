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
});
