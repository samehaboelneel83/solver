import { describe, expect, it } from "vitest";
import { checkIrShape } from "../ir/validate";
import { EMPTY_MODEL, publishable, type FormDraft } from "./draftIr";
import { proposeDraft, recipeFor, type Kind } from "./draftFromWords";

const empty: FormDraft = { sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } };
const n = (name: string) => ({ name, data_type: "number" });
const KINDS: Kind[] = [
  { name: "project", attributes: [n("benefit"), n("capex"), { name: "committed", data_type: "boolean" }] },
  { name: "year", role: "time", attributes: [n("budget"), n("weight")] },
  { name: "warehouse", role: "location", attributes: [n("capacity"), n("fixed_cost")] },
  { name: "store", role: "location", attributes: [n("demand")] },
  { name: "truck_type", attributes: [n("load"), n("price")] },
  { name: "candidate_site", role: "location", attributes: [n("rent")] },
  { name: "zone", role: "location", attributes: [n("population"), n("vulnerability")] },
];
const DATA = [{ name: "unit_cost", index: ["warehouse", "store"] }, { name: "within_15", index: ["zone", "candidate_site"] }];
const valid = (d: FormDraft) => expect(checkIrShape({ ...EMPTY_MODEL, ...d })).toBeNull();

describe("describe it -> a first draft (benchmark, October 2026)", () => {
  it("reads projects within a budget, with the budget and the most chosen as written", () => {
    const p = proposeDraft("Choose up to 3 projects to fund with a budget of 2.5 million, the most benefit first", KINDS, DATA)!;
    expect(p.recipe).toBe("selection");
    expect(p.missing).toEqual([]);
    expect(p.choices.join("\n")).toMatch(/Chosen from: project — you wrote “projects”/);
    expect(p.choices.join("\n")).toMatch(/Budget: 2500000/);
    const d = p.apply!(empty);
    valid(d);
    expect(d.constraints.map((c) => [c.id, c.right])).toEqual([["budget", { const: 2500000 }], ["at_most_chosen", { const: 3 }], ["must_have", { const: 1 }]]);
  });

  it("reads projects over years as phasing, the budget from each year", () => {
    const p = proposeDraft("Which projects to start in each year of the next five years, within each year's budget", KINDS, DATA)!;
    expect(p.recipe).toBe("phasing");
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(d.variables.start).toEqual({ index: ["project", "year"], domain: "binary" });
  });

  it("reads a supply network: which warehouses to open, shipping, one supplier, shortage, trucks", () => {
    const p = proposeDraft("Which warehouses to open to deliver to every store from a single warehouse, with a fleet of trucks; "
      + "unmet demand has a penalty of 500 a unit", KINDS, DATA)!;
    expect(p.recipe).toBe("network");
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(Object.keys(d.variables)).toEqual(["ship", "open", "short", "served_by", "vehicles"]);
    expect(d.objective.terms.find((t) => t.id === "shortage")!.expression).toMatchObject({ sum: { mul: [{ const: 500 }, {}] } });
  });

  it("reads coverage, and says what is missing instead of guessing", () => {
    const p = proposeDraft("Open candidate sites so every zone is within 15 minutes of one, most vulnerable population first, budget 40000", KINDS, DATA)!;
    expect(p.recipe).toBe("coverage");
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(d.parameters.within_15).toEqual({ index: ["zone", "candidate_site"] });
    const lacking = proposeDraft("Open candidate sites so every zone is within 15 minutes of one", KINDS, [])!;
    expect(lacking.apply).toBeNull();
    expect(lacking.missing[0]).toMatch(/0\/1 data over candidate_site and zone/);
  });

  it("says nothing on too few words, and ranks recipes by the words", () => {
    expect(proposeDraft("help", KINDS, DATA)).toBeNull();
    expect(recipeFor("ship from depots to customers by truck")[0].recipe).toBe("network");
  });

  it("shares land among crops: size, worth through data, a water limit, where allowed, shares (benchmark re-test, October 2026)", () => {
    const kinds: Kind[] = [
      { name: "parcel", attributes: [n("area_feddan")] },
      { name: "crop", attributes: [n("water_m3_per_feddan"), n("min_share"), n("max_share")] },
    ];
    const data = [{ name: "profit_per_feddan", index: ["parcel", "crop"] }, { name: "suitable", index: ["crop", "parcel"] }];
    const p = proposeDraft("Which crops to plant on each parcel, all the land, with a water quota of 18,920,000 m3", kinds, data)!;
    expect(p.recipe).toBe("allocation");
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(d.variables.amount).toMatchObject({ index: ["parcel", "crop"], domain: "continuous" });
    expect(d.constraints.map((c) => c.id)).toEqual(["size_of_each", "shared_limit", "only_where_allowed", "least_share", "most_share"]);
    expect(d.constraints[0].relation).toBe("=");
    expect(d.constraints[1]).toMatchObject({ right: { const: 18920000 } });
    expect(JSON.stringify(d.constraints[2])).toContain('"par":"suitable","index":["o","i"]');
  });

  it("routes a trips table over the roads, widened within a budget (benchmark re-test, October 2026)", () => {
    const kinds: Kind[] = [
      { name: "zone", attributes: [] },
      { name: "road_link", attributes: [n("travel_minutes"), n("capacity_vph"), n("extra_capacity"), n("widen_cost_m")] },
    ];
    const data = [{ name: "od_trips", index: ["zone", "zone"] }];
    const links = [{ name: "from_zone", from: "road_link", to: "zone" }, { name: "to_zone", from: "road_link", to: "zone" }];
    const text = "Morning commute trips between zones congest the roads: which roads to widen with a budget of 30 million";
    expect(recipeFor(text)[0].recipe).toBe("flow");
    const p = proposeDraft(text, kinds, data, undefined, links)!;
    expect(p.missing).toEqual([]);
    expect(p.choices).toContain("A road starts at from_zone and ends at to_zone — their names");
    const d = p.apply!(empty);
    // "congest" asks for time that grows as a road fills (benchmark round 4), not a hard limit.
    expect(d.constraints.map((c) => c.id)).toEqual(["trips_arrive", "upgrade_budget", "load_in_pieces", "load_1_width", "load_2_width", "load_3_width", "load_4_width"]);
    expect(d.constraints[1]).toMatchObject({ right: { const: 30 } });
    const plain = proposeDraft("Route the commute trips between zones over the roads: which roads to widen with a budget of 30 million", kinds, data, undefined, links)!;
    expect(plain.apply!(empty).constraints.map((c) => c.id)).toEqual(["trips_arrive", "upgrade_budget", "road_capacity"]);
    // Without the two links it says what is missing instead of guessing.
    expect(proposeDraft(text, kinds, data)!.missing[0]).toMatch(/each linked twice to zone/);
  });

  it("orders stock per product, week and warehouse from a forecast, within room, lost sales at a cost (benchmark re-test, October 2026)", () => {
    const kinds: Kind[] = [
      { name: "sku", attributes: [n("unit_cost"), n("holding_cost"), n("pallets")] },
      { name: "week", role: "time", attributes: [] },
      { name: "warehouse", role: "location", attributes: [n("pallet_capacity")] },
    ];
    const data = [{ name: "demand_forecast", index: ["sku", "warehouse", "week"] }, { name: "on_hand", index: ["warehouse", "sku"] }];
    const text = "How much of each SKU to reorder every week at each warehouse to meet the forecast; lost sales cost 40 a unit";
    expect(recipeFor(text)[0].recipe).toBe("inventory");
    const p = proposeDraft(text, kinds, data)!;
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(d.variables.order).toMatchObject({ index: ["sku", "warehouse", "week"] });
    expect(d.constraints.map((c) => c.id)).toEqual(["stock_balance", "storage"]);
    expect(JSON.stringify(d.constraints[0])).toContain('"par":"on_hand","index":["l","p"]');
    expect(d.objective.terms.map((x) => [x.id, x.weight])).toEqual([["ordering_cost", 1], ["holding_cost", 1], ["lost_sales", 1]]);
  });

  it("covers what the reach data joins the sites to, not a kind only named, with seats and the budget in the costs' units", () => {
    const kinds: Kind[] = [
      { name: "candidate_site", attributes: [n("monthly_cost_k"), n("capacity")] },
      { name: "town", attributes: [n("population")] },
      { name: "restricted_zone", attributes: [] },
    ];
    const data = [{ name: "within_30_min", index: ["candidate_site", "town"] }];
    const p = proposeDraft("Open candidate sites away from the restricted zone so people are within 30 minutes; budget of 150,000 a month, capacity matters", kinds, data)!;
    expect(p.recipe).toBe("coverage");
    expect(p.choices.join("\n")).toMatch(/Cover: town —/);
    expect(p.choices.join("\n")).not.toMatch(/Cover: restricted_zone/);
    expect(p.choices.join("\n")).toMatch(/Budget in the costs' units: 150/);
    const d = p.apply!(empty);
    valid(d);
    expect(Object.keys(d.variables)).toContain("seated");
    expect(d.constraints.find((c) => c.id === "budget")).toMatchObject({ right: { const: 150 } });
  });
});

describe("the problem's own words (benchmark round 3)", () => {
  it("are taken from the workspace by the first problem that opens them, not offered to the next", async () => {
    const { keepWords, keepProblemWords, wordsFor } = await import("./draftFromWords");
    localStorage.clear();
    keepWords(9, "Choose projects within a budget");
    expect(wordsFor(9, 31)).toBe("Choose projects within a budget");
    expect(wordsFor(9, 32)).toBe("");
    expect(wordsFor(9, 31)).toBe("Choose projects within a budget");
    keepProblemWords(32, "Route the trucks");
    expect(wordsFor(9, 32)).toBe("Route the trucks");
  });
});

describe("reading the words and the data better (benchmark round 3)", () => {
  it("takes a budget in kEGP as thousands, and a blocked project as never chosen", () => {
    const kinds: Kind[] = [{ name: "project", attributes: [n("benefit"), n("cost_kegp"), { name: "blocked_by_construction", data_type: "boolean" }] }];
    const p = proposeDraft("Fund projects within a budget of 150000 kEGP, most benefit first. A project blocked by construction can never be chosen.", kinds, [])!;
    expect(p.recipe).toBe("selection");
    const d = p.apply!(empty);
    valid(d);
    expect(d.constraints.find((c) => c.id === "budget")).toMatchObject({ right: { const: 150000 } });
    expect(d.constraints.map((c) => c.id)).toEqual(["budget", "never_chosen"]);
    expect(JSON.stringify(d.constraints[1])).toContain('"attr":"blocked_by_construction","op":"=","value":true');
  });

  it("does not take travel minutes for who is within reach, and says how to make it", () => {
    const kinds: Kind[] = [{ name: "candidate_site", attributes: [n("cost")] }, { name: "district", attributes: [n("population")] }];
    const p = proposeDraft("Open candidate sites so every district is covered within 15 minutes", kinds, [{ name: "site_district_min", index: ["candidate_site", "district"] }])!;
    expect(p.recipe).toBe("coverage");
    expect(p.apply).toBeNull();
    expect(p.missing.join(" ")).toMatch(/site_district_min holds travel times or distances, not yes\/no/);
  });

  it("weights coverage by the field the words name, and counts places a base serves", () => {
    const kinds: Kind[] = [{ name: "base", attributes: [n("fixed_cost"), n("capacity_units")] },
      { name: "town", attributes: [n("population"), n("incident_count")] }];
    const p = proposeDraft("Open bases so towns are within reach; each base can serve at most capacity_units towns. Weight coverage by incident_count.",
      kinds, [{ name: "within_30", index: ["base", "town"] }])!;
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(JSON.stringify(d.objective.terms[0].expression)).toContain('"name":"incident_count"');
    expect(JSON.stringify(d.objective.terms[0].expression)).not.toContain("population");
    expect(d.variables.served_by).toMatchObject({ index: ["town", "base"], domain: "binary" });
    expect(d.constraints.map((c) => c.id)).toEqual(expect.arrayContaining(["served_if_covered", "served_within_reach", "serves_at_most"]));
  });

  it("makes a crop's worth its yield times its price, less its cost", () => {
    const kinds: Kind[] = [{ name: "parcel", attributes: [n("area_feddan")] },
      { name: "crop", attributes: [n("yield_t_per_feddan"), n("price_egp_per_t"), n("cost_egp_per_feddan")] }];
    const p = proposeDraft("Which crops to plant on each parcel", kinds, [])!;
    expect(p.recipe).toBe("allocation");
    const d = p.apply!(empty);
    valid(d);
    const goal = JSON.stringify(d.objective.terms[0].expression);
    expect(goal).toContain("yield_t_per_feddan");
    expect(goal).toContain("price_egp_per_t");
    expect(goal).toContain("cost_egp_per_feddan");
  });
});

describe("each place to its nearest open site (benchmark round 4)", () => {
  it("reads 'minimise response time' as sending each district to one open station", () => {
    const kinds: Kind[] = [
      { name: "station", attributes: [n("build_cost"), { name: "existing", data_type: "boolean" }] },
      { name: "district", attributes: [n("population"), n("calls_per_day")] },
    ];
    const data = [{ name: "station_district_min", index: ["station", "district"] }];
    const text = "Open 5 stations so each district is served by its nearest station, minimise response time weighted by calls_per_day, never more than 15 minutes";
    expect(recipeFor(text)[0].recipe).toBe("assignment");
    const p = proposeDraft(text, kinds, data)!;
    expect(p.missing).toEqual([]);
    const d = p.apply!(empty);
    valid(d);
    expect(d.constraints.map((c) => c.id)).toEqual(["one_site_each", "only_from_open", "within_reach", "sites_open", "existing_stay_open"]);
    expect(d.constraints.find((c) => c.id === "within_reach")).toMatchObject({ right: { const: 15 } });
    expect(JSON.stringify(d.objective.terms[0].expression)).toContain('"name":"calls_per_day"');
  });
});

describe("reading more of the words (benchmark round 4)", () => {
  const text = (a: string, data_type = "text", enum_values: string[] | null = null) => ({ name: a, data_type, enum_values });
  const projects: Kind[] = [
    { name: "project", attributes: [n("benefit_per_megp"), n("veh_hours_saved_per_day"), n("cost_megp"), text("type"), text("in_district")] },
    { name: "district", attributes: [n("population")] },
  ];

  it("takes the worth the words name, a limit per type, and at least one in every district through the link", () => {
    const p = proposeDraft("Fund projects with a budget of 250 M EGP for the most veh_hours_saved_per_day: at most 8 parking projects, "
      + "and every district gets at least one project", projects, [], undefined, [{ name: "in_district", from: "project", to: "district" }])!;
    expect(p.recipe).toBe("selection");
    expect(p.missing).toEqual([]);
    expect(p.choices.join("\n")).toMatch(/Worth: veh_hours_saved_per_day/);
    expect(p.choices.join("\n")).not.toMatch(/At most chosen/);
    const d = p.apply!(empty);
    expect(checkIrShape(publishable({ ...EMPTY_MODEL, ...d }))).toBeNull();
    expect(d.constraints.map((c) => c.id)).toEqual(["budget", "at_most_parking", "one_per_district"]);
    expect(d.constraints[1]).toMatchObject({ right: { const: 8 }, left: { sum: { var: "choose" }, over: [{ set: "project", where: [{ attr: "type", op: "=", value: "parking" }] }] } });
    expect(d.constraints[2]).toMatchObject({ relation: ">=", forall: [{ index: "d", set: "district" }],
      left: { over: [{ set: "project", via: { rel: "in_district", to: "d" } }] } });
    expect(d.objective.terms[0].expression).toMatchObject({ sum: { mul: [{ attr: { name: "veh_hours_saved_per_day" } }, {}] } });
  });

  it("takes the value from a list field holding the word, and says what is missing for a district rule with no link", () => {
    const kinds: Kind[] = [{ name: "project", attributes: [n("benefit"), n("cost"), text("category", "enum", ["Widening", "Parking", "Signal"])] },
      { name: "district", attributes: [] }];
    const p = proposeDraft("Fund projects with a budget of 100: no more than 2 signal projects, at least one in every district", kinds, [])!;
    const d = p.apply!(empty);
    expect(d.constraints[1]).toMatchObject({ id: "at_most_signal", left: { over: [{ where: [{ attr: "category", value: "Signal" }] }] } });
    expect(d.constraints).toHaveLength(2);
    expect(p.choices.join("\n")).toMatch(/Not added: at least one in every district .* no project is linked to a district/);
  });

  it("takes the opening cost the words name, never `rent` inside `current_inventory_t`", () => {
    const kinds: Kind[] = [{ name: "warehouse", attributes: [n("current_inventory_t"), n("capacity_t"), n("fixed_cost_egp_yr")] },
      { name: "store", attributes: [n("demand_t"), n("shortage_penalty")] }];
    const data = [{ name: "unit_cost", index: ["warehouse", "store"] }];
    const p = proposeDraft("Which warehouses to open (fixed_cost_egp_yr), ship to every store, unmet demand allowed at a penalty", kinds, data)!;
    expect(p.recipe).toBe("network");
    expect(p.choices.join("\n")).toMatch(/Opening cost: fixed_cost_egp_yr/);
    const d = p.apply!(empty);
    expect(d.objective.terms.find((t) => t.id === "shortage")).toMatchObject({ weight: 1,
      expression: { sum: { mul: [{ attr: { of: "c", name: "shortage_penalty" } }, { var: "short" }] } } });
    const q = proposeDraft("Which warehouses to open, ship to every store", [{ name: "warehouse", attributes: [n("current_inventory_t"), n("capacity_t")] },
      { name: "store", attributes: [n("demand_t")] }], data)!;
    expect(q.choices.join("\n")).not.toMatch(/Opening cost/);
  });

  it("takes a crop's least and most area as amounts, and a share as of the land that can hold it", () => {
    const kinds: Kind[] = [{ name: "parcel", attributes: [n("area_feddan")] }, { name: "crop", attributes: [n("profit"), n("min_area"), n("max_area")] }];
    const data = [{ name: "suitable", index: ["parcel", "crop"] }];
    const p = proposeDraft("Allocate land among crops on each parcel for the most profit", kinds, data)!;
    expect(p.recipe).toBe("allocation");
    const d = p.apply!(empty);
    valid(d);
    expect(d.constraints.find((c) => c.id === "least_amount")).toMatchObject({ relation: ">=", right: { attr: { name: "min_area" } } });
    expect(d.constraints.find((c) => c.id === "most_amount")).toMatchObject({ relation: "<=", right: { attr: { name: "max_area" } } });
    expect(d.constraints.some((c) => c.id === "least_share" || c.id === "most_share")).toBe(false);
  });
});
