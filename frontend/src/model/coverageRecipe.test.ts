import { describe, expect, it } from "vitest";
import { applyCoverage } from "./coverageRecipe";
import { printRule } from "./formula";
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

  it("staffs each open site from a pool, within each one's limit and its link's reach", () => {
    const d = applyCoverage(empty, { ...recipe, staff: { kind: "medical_team", capacity: "max_centres",
      via: { rel: "base_hospital", end: "from", kind: "hospital", reach: "hosp_reach", reachIndex: ["hospital", "site"] } } });
    expect(d.sets).toEqual(["site", "zone", "hospital", "medical_team"]);
    expect(d.variables.assign).toEqual({ index: ["medical_team", "site"], domain: "binary" });
    expect(d.parameters.hosp_reach).toEqual({ index: ["hospital", "site"] });
    const rules = Object.fromEntries(d.constraints.map((c) => [c.id, printRule(c)]));
    expect(rules.one_per_open_site).toBe("for each s in site: sum(assign[t, s] for t in medical_team) = open[s]");
    expect(rules.staff_capacity).toBe("for each t in medical_team: sum(assign[t, s] for s in site) <= max_centres[t]");
    expect(rules.staff_reach).toBe("for each t in medical_team, s in site: assign[t, s] <= sum(hosp_reach[h, s] for h in hospital from t by base_hospital)");
  });

  it("keeps sites linked to a risk area closed, unless they cope", () => {
    const d = applyCoverage(empty, { ...recipe, avoid: { rel: "in_outage_area", end: "from", kind: "outage_risk_area", unless: "has_generator" } });
    const rule = d.constraints.find((c) => c.id === "avoid_outage_risk_area")!;
    expect(printRule(rule)).toBe("for each s in site where has_generator = false: sum(open[s] for a in outage_risk_area from s by in_outage_area) <= 0");
    expect(d.sets).toContain("outage_risk_area");
  });

  it("seats a covered place's people at open sites within reach, none over its seats", () => {
    const d = applyCoverage(empty, { ...recipe, seats: { capacity: "seats", demand: ["population", "share_over65"] } });
    expect(d.variables.seated).toEqual({ index: ["zone", "site"], domain: "continuous", lower: 0 });
    const rules = Object.fromEntries(d.constraints.map((c) => [c.id, printRule(c)]));
    expect(rules.seats_for_covered).toBe("for each p in zone: sum(seated[p, s] for s in site) >= population[p] * share_over65[p] * covered[p]");
    expect(rules.seats_within_reach).toBe("for each p in zone, s in site: seated[p, s] <= population[p] * share_over65[p] * covers[p, s]");
    expect(rules.seats_capacity).toBe("for each s in site: sum(seated[p, s] for p in zone) <= seats[s] * open[s]");
  });

  it("gives an open site as many staff as its field asks", () => {
    const d = applyCoverage(empty, { ...recipe, staff: { kind: "medical_team", needs: "teams_needed" } });
    expect(printRule(d.constraints.find((c) => c.id === "staff_per_open_site")!))
      .toBe("for each s in site: sum(assign[t, s] for t in medical_team) = teams_needed[s] * open[s]");
  });

  it("seats only the share that needs a seat at once", () => {
    const d = applyCoverage(empty, { ...recipe, seats: { capacity: "seats", demand: ["population"], share: 0.05 } });
    expect(printRule(d.constraints.find((c) => c.id === "seats_for_covered")!))
      .toBe("for each p in zone: sum(seated[p, s] for s in site) >= population[p] * 0.05 * covered[p]");
  });

  it("never leaves out a place this needy", () => {
    const d = applyCoverage(empty, { ...recipe, mustCover: { field: "vulnerability", atLeast: 4 } });
    expect(printRule(d.constraints.find((c) => c.id === "must_cover")!)).toBe("for each p in zone where vulnerability >= 4: covered[p] >= 1");
  });
});
