import { describe, expect, it } from "vitest";
import { suggest } from "./describeProblem";

describe("describe it in words (improvement plan 5.6)", () => {
  it("points a placement-and-roster problem at the right examples and tools", () => {
    const got = suggest("Where to pre-position 40 pump trucks in 6 yards so every flood hotspot is within 15 minutes "
      + "of driving, then a crew roster for 120 operators with 10 hours rest between shifts. Data is a GeoJSON map.");
    const keys = got.map((s) => s.key);
    expect(keys.slice(0, 2).sort()).toEqual(["emergency_coverage", "weekly_rota"]);
    expect(keys).toEqual(expect.arrayContaining(["within", "rest", "map_layers"]));
    expect(got.find((s) => s.key === "rest")?.why).toContain("“rest”");
  });

  it("points the user trial's heatwave problem at the cooling-centre example first", () => {
    const got = suggest("During the heatwave we must open cooling centres in Giza. Choose which candidate sites to open so that "
      + "vulnerable zones are within 1.5 km of an open centre, over-65s first. Avoid sites inside outage risk areas unless they have a generator.");
    expect(got.find((s) => s.kind === "example")?.key).toBe("heatwave_cooling");
  });

  it("says nothing for too little to go on, and offers only examples this install has", () => {
    expect(suggest("help")).toEqual([]);
    expect(suggest("blend the cheapest feed mix from ingredients", ["weekly_rota"]).some((s) => s.kind === "example")).toBe(false);
  });
});
