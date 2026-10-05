import { describe, expect, it } from "vitest";
import { inside, parseLatLon, toLocal, toLonLat, type Ring } from "./geo";

const L: Ring = [[0, 0], [30, 0], [30, 12], [18, 12], [18, 20], [0, 20]];

describe("site geometry", () => {
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

  it("tells inside from outside", () => {
    expect(inside([5, 15], L)).toBe(true);
    expect(inside([25, 15], L)).toBe(false);
  });

  it("reads a pasted position", () => {
    expect(parseLatLon("30.0444, 31.2357")).toEqual([31.2357, 30.0444]);
    expect(parseLatLon("hello")).toBeNull();
  });
});
