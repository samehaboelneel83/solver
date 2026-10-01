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

  it("says nothing for too little to go on, and offers only examples this install has", () => {
    expect(suggest("help")).toEqual([]);
    expect(suggest("blend the cheapest feed mix from ingredients", ["weekly_rota"]).some((s) => s.kind === "example")).toBe(false);
  });
});
