import { describe, expect, it } from "vitest";
import { leftOut } from "./MeasureFromMap";

describe("leftOut", () => {
  it("names places too far from the lines, and says how to bring them in", () => {
    const said = leftOut({ kind: "distance", metric: "x", from: "yard", to: "hotspot", computed_at: "", off_network: ["H04 (602 m)", "H11 (770 m)"] }, 500);
    expect(said).toContain("2 places are further than 500 m");
    expect(said).toContain("H04 (602 m)");
    expect(said).toContain("Join places up to");
  });
  it("is quiet when everything was reached", () => {
    expect(leftOut({ kind: "within", metric: "x", from: "a", to: "b", computed_at: "" }, 500)).toBeNull();
  });
});

describe("areaKinds", () => {
  it("puts measured areas first and leaves points out", async () => {
    const { areaKinds } = await import("./MeasureFromMap");
    const k = (id: number, name: string, attrs: string[]) =>
      ({ id, name, attributes: attrs.map((a) => ({ name: a, data_type: a === "shape" ? "geometry" : "number" })) }) as never;
    const kinds = [k(1, "hospital", ["shape"]), k(2, "district", ["shape", "area_m2"]), k(3, "flood_zone", ["shape"])];
    expect(areaKinds(kinds).map((t: { name: string }) => t.name)).toEqual(["district", "flood_zone"]);
  });
});

describe("the way to bring places in", () => {
  it("names the field only where it is shown (benchmark round 5)", () => {
    const source = { kind: "distance", metric: "time", from: "cell", to: "station", computed_at: "", off_network: ["C1 (900 m)"] };
    expect(leftOut(source, 500, false)).toMatch(/measure “along a lines layer I imported”/);
    expect(leftOut(source, 500)).toMatch(/Widen “Join places up to”/);
  });
});

describe("pairs with no road between them", () => {
  it("says the value they read and which they are (benchmark round 5)", () => {
    const said = leftOut({ kind: "distance", metric: "time", from: "base", to: "zone", computed_at: "", no_road: 2, far: 885,
      no_road_pairs: ["B1 → Z9", "B2 → Z9"] } as never, 500);
    expect(said).toBe("2 pairs have no road between them; a model reads each as 885 (ten times the longest), so it never takes one as near: B1 → Z9, B2 → Z9.");
  });
});
