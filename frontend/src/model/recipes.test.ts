import { writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { checkIrShape } from "../ir/validate";
import { applyAllocation, applyFlow, applyNetwork, applyPhasing, applySelection } from "./recipes";
import { printRule } from "./formula";
import { EMPTY_MODEL, publishable, type FormDraft } from "./draftIr";

const empty: FormDraft = { sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } };
const ir = (d: FormDraft) => ({ ...EMPTY_MODEL, ...d });
const rules = (d: FormDraft) => Object.fromEntries(d.constraints.map((c) => [c.id, printRule(c)]));
const made: Record<string, unknown> = {};

describe("more recipes (benchmark, October 2026)", () => {
  it("chooses projects within a budget for the most value", () => {
    const d = applySelection(empty, { items: "project", value: "benefit", cost: "capex", budget: 500, atMost: 3, mustHave: "committed" });
    expect(checkIrShape(ir(d))).toBeNull();
    expect(rules(d)).toEqual({
      budget: "sum(capex[i] * choose[i] for i in project) <= 500",
      at_most_chosen: "sum(choose[i] for i in project) <= 3",
      must_have: "for each i in project where committed = true: choose[i] >= 1",
    });
    expect(d.objective).toMatchObject({ sense: "maximize" });
    made.selection = ir(d);
  });

  it("designs a network: open depots, ship, one supplier each, shortage at a price, a fleet by type", () => {
    const d = applyNetwork(empty, { sources: "depot", customers: "store", demand: "demand", unitCost: "unit_cost", unitCostIndex: ["depot", "store"],
      capacity: "capacity", openCost: "fixed_cost", singleSource: true, shortagePenalty: 1000, fleet: { kind: "truck_type", capacity: "load", cost: "price" } });
    expect(checkIrShape(ir(d))).toBeNull();
    expect(Object.keys(d.variables)).toEqual(["ship", "open", "short", "served_by", "vehicles"]);
    const r = rules(d);
    expect(r.demand_met).toBe("for each c in store: sum(ship[s, c] for s in depot) + short[c] >= demand[c]");
    expect(r.ship_only_if_served).toBe("for each s in depot, c in store: ship[s, c] <= demand[c] * served_by[s, c]");
    expect(r.source_capacity).toBe("for each s in depot: sum(ship[s, c] for c in store) <= capacity[s] * open[s]");
    expect(r.fleet_carries).toBe("for each s in depot: sum(ship[s, c] for c in store) <= sum(load[t] * vehicles[s, t] for t in truck_type)");
    expect(d.objective.terms.map((t) => [t.id, t.weight])).toEqual([["shipping_cost", 1], ["opening_cost", 1], ["fleet_cost", 1], ["shortage", 1000]]);
    expect(d.sets).toEqual(["depot", "store", "truck_type"]);
    made.network = ir(d);
    // The plainest form: ship from fixed sources, nothing else.
    const plain = applyNetwork(empty, { sources: "depot", customers: "store", demand: "demand", unitCost: "unit_cost", unitCostIndex: ["store", "depot"] });
    expect(Object.keys(rules(plain))).toEqual(["demand_met"]);
    expect(JSON.stringify(plain.objective)).toContain('"par":"unit_cost","index":["c","s"]');
  });

  it("phases projects over periods within each period's budget, sooner worth more", () => {
    const d = applyPhasing(empty, { items: "project", periods: "year", value: "benefit", cost: "capex", budget: "budget", weight: "weight" });
    expect(checkIrShape(ir(d))).toBeNull();
    expect(rules(d)).toEqual({
      start_once: "for each i in project: sum(start[i, t] for t in year) <= 1",
      period_budget: "for each t in year: sum(capex[i] * start[i, t] for i in project) <= budget[t]",
    });
    expect(d.objective.terms[0].id).toBe("value_sooner");
    made.phasing = ir(d);
  });

  it("shares land among crops within a water limit, only where allowed, within shares (benchmark re-test, October 2026)", () => {
    const d = applyAllocation(empty, { items: "parcel", options: "crop", size: "area", worth: { field: "profit" },
      use: { field: "water", limit: 100 }, allowed: { data: "suitable", index: ["parcel", "crop"] }, maxShare: "max_share", all: false });
    expect(checkIrShape(ir(d))).toBeNull();
    expect(rules(d)).toEqual({
      size_of_each: "for each i in parcel: sum(amount[i, o] for o in crop) <= area[i]",
      shared_limit: "sum(water[o] * amount[i, o] for i in parcel, o in crop) <= 100",
      only_where_allowed: "for each i in parcel, o in crop: amount[i, o] <= area[i] * suitable[i, o]",
      most_share: "for each o in crop: sum(amount[i, o] for i in parcel) <= max_share[o] * sum(area[i] for i in parcel)",
    });
    made.allocation = ir(d);
  });

  it("routes trips between zones over the roads within capacity, widening roads within a budget (benchmark re-test, October 2026)", () => {
    const d = applyFlow(empty, { nodes: "junction", arcs: "road", startsAt: "road_from", endsAt: "road_to", trips: "trips", time: "minutes",
      capacity: "capacity", upgrade: { added: "extra", cost: "widen_cost", budget: 10 } });
    const published = publishable(ir(d));
    expect(checkIrShape(published)).toBeNull();
    expect(rules(d)).toEqual({
      trips_arrive: "for each o in junction, n in junction where n != o: sum(flow[a, o] for a in road to n by road_to) - sum(flow[a, o] for a in road to n by road_from) = trips[o, n]",
      upgrade_budget: "sum(widen_cost[a] * upgrade[a] for a in road) <= 10",
      road_capacity: "for each a in road: sum(flow[a, o] for o in junction) <= capacity[a] + extra[a] * upgrade[a]",
    });
    expect(published.relationships).toEqual(["road_from", "road_to"]);
    made.flow = published;
    if (process.env.RECIPES_OUT) writeFileSync(process.env.RECIPES_OUT, JSON.stringify(made, null, 1));
  });

  it("keeps what the draft had and gives new names", () => {
    const once = applySelection(empty, { items: "project", value: "benefit", cost: "capex", budget: 5 });
    const twice = applySelection(once, { items: "project", value: "benefit", cost: "capex", budget: 9 });
    expect(Object.keys(twice.variables)).toEqual(["choose", "choose_2"]);
    expect(twice.constraints.map((c) => c.id)).toEqual(["budget", "budget_2"]);
  });
});
