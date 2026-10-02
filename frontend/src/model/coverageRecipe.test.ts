import { describe, expect, it } from "vitest";
import { applyCoverage } from "./coverageRecipe";
import type { FormDraft } from "./draftIr";

const empty: FormDraft = { sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } };
const recipe = { sites: "site", places: "zone", reach: "covers", reachIndex: ["zone", "site"], cost: "cost_egp_day", budget: 60000,
  weights: ["population", "vulnerability"], coverAll: false };

describe("the coverage recipe", () => {
  it("writes the decisions, the reach rule, the budget and the goals in order", () => {
    const d = applyCoverage(empty, recipe);
    expect(d.sets).toEqual(["site", "zone"]);
    expect(d.parameters).toEqual({ covers: { index: ["zone", "site"] } });
    expect(d.variables).toEqual({ open: { index: ["site"], domain: "binary" }, covered: { index: ["zone"], domain: "binary" } });
    expect(d.constraints.map((c) => c.id)).toEqual(["covered_needs_open", "budget"]);
    // The reach data is read in its own index order.
    expect(JSON.stringify(d.constraints[0])).toContain('"par":"covers","index":["p","s"]');
    expect(d.constraints[1]).toMatchObject({ relation: "<=", right: { const: 60000 } });
    expect(d.objective).toMatchObject({ sense: "maximize", mode: "lex" });
    expect(d.objective.terms.map((t) => t.id)).toEqual(["covered_worth", "cost"]);
    expect(JSON.stringify(d.objective.terms[0])).toContain('"name":"population"');
  });

  it("covers every place at the least cost when asked, and keeps what the draft had", () => {
    const had = applyCoverage(empty, recipe);
    const d = applyCoverage(had, { ...recipe, coverAll: true, budget: undefined });
    expect(Object.keys(d.variables)).toEqual(["open", "covered", "open_2"]);
    expect(d.constraints.map((c) => c.id)).toEqual(["covered_needs_open", "budget", "every_place_covered"]);
    expect(d.objective).toMatchObject({ sense: "minimize", mode: "weighted" });
  });
});
