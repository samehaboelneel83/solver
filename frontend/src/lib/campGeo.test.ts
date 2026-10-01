import { describe, expect, it } from "vitest";
import type { Ring } from "../api/camps";
import { area, axisWalls, circle, doorAt, freshName, inside, orthogonal, parseLatLon, snap, toLocal, toLonLat } from "./campGeo";

const L: Ring = [[0, 0], [30, 0], [30, 12], [18, 12], [18, 20], [0, 20]];

describe("camp geometry", () => {
  it("goes to longitude and latitude and back to the centimetre", () => {
    const origin: [number, number] = [31.6, 30.1];
    const there = toLonLat([250, -120], origin);
    const back = toLocal(there, origin);
    expect(back[0]).toBeCloseTo(250, 2);
    expect(back[1]).toBeCloseTo(-120, 2);
    // About 96 km to a degree of longitude at 30° N, 111 km to one of latitude.
    expect((there[0] - origin[0]) * 96_000).toBeGreaterThan(240);
    expect(toLonLat([0, 1000], origin)[1] - origin[1]).toBeCloseTo(1000 / 110_860, 4);
  });

  it("measures, snaps and keeps walls straight", () => {
    expect(area(L)).toBe(30 * 12 + 18 * 8);
    expect(inside([5, 15], L)).toBe(true);
    expect(inside([25, 15], L)).toBe(false);
    expect(snap([1.26, 3.74], 0.5)).toEqual([1.5, 3.5]);
    expect(orthogonal([0, 0], [5, 0.4])).toEqual([5, 0]);
    // A drawn circle encloses the circle: never smaller, about 1% larger.
    const round = area(circle([0, 0], 1.2));
    expect(round).toBeGreaterThan(Math.PI * 1.44);
    expect(round / (Math.PI * 1.44)).toBeLessThan(1.02);
  });

  it("puts a door on the nearest horizontal or vertical wall, kept on it", () => {
    expect(axisWalls(L)).toHaveLength(6);
    expect(doorAt([10, 0.6], L, 2, 0.5)).toEqual([[9, 0], [11, 0]]);
    expect(doorAt([29.7, 11.5], L, 2, 0.5)).toEqual([[30, 10], [30, 12]]);
    const slanted: Ring = [[0, 0], [10, 0], [0, 10]];
    expect(doorAt([5.2, 5.2], slanted, 2, 0.5, 1)).toBeNull();
  });

  it("reads a pasted position and names shapes", () => {
    expect(parseLatLon("30.0444, 31.2357")).toEqual([31.2357, 30.0444]);
    expect(parseLatLon("hello")).toBeNull();
    expect(freshName("D", ["D1", "D2", "D4"])).toBe("D3");
  });
});
