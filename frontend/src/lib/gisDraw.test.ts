import { describe, expect, it } from "vitest";
import type { GisFeature } from "../api/gis";
import { extentOf, hit, prepare } from "./gisDraw";

const O: [number, number] = [31.6, 30.1];
// About 1 m in degrees at 30° N.
const dx = 1 / 96_490, dy = 1 / 110_860;
const at = (x: number, y: number): [number, number] => [O[0] + x * dx, O[1] + y * dy];

const FEATURES: GisFeature[] = [
  { type: "Feature", geometry: { type: "Polygon", coordinates: [[at(0, 0), at(20, 0), at(20, 10), at(0, 10), at(0, 0)], [at(5, 2), at(8, 2), at(8, 5), at(5, 5), at(5, 2)]] },
    properties: { layer: "Buildings", kind: "polygon" } },
  { type: "Feature", geometry: { type: "LineString", coordinates: [at(-5, -5), at(30, -5)] }, properties: { layer: "Roads", kind: "line" } },
  { type: "Feature", geometry: { type: "Point", coordinates: at(10, 8) }, properties: { layer: "Trees", kind: "point" } },
];

describe("GIS features on the map", () => {
  const items = prepare(FEATURES, O);

  it("prepares features in metres around the origin", () => {
    const [x0, y0, x1, y1] = extentOf(items)!;
    expect(x0).toBeCloseTo(-5, 1);
    expect(y0).toBeCloseTo(-5, 1);
    expect(x1).toBeCloseTo(30, 1);
    expect(y1).toBeCloseTo(10, 1);
  });

  it("finds the point first, then a line, then the area around the pointer, but not inside a hole", () => {
    const all = () => true;
    expect(hit(items, [10.05, 8], 0.05, all)?.layer).toBe("Trees");
    expect(hit(items, [12, -5.1], 0.05, all)?.layer).toBe("Roads");
    expect(hit(items, [15, 5], 0.05, all)?.layer).toBe("Buildings");
    expect(hit(items, [6.5, 3.5], 0.05, all)).toBeNull();
    expect(hit(items, [15, 5], 0.05, (layer) => layer !== "Buildings")).toBeNull();
  });
});
