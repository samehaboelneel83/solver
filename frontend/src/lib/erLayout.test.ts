import { describe, expect, it } from "vitest";
import { footprint, petalAngles, placePetals, ringRadius, type Petal } from "./erLayout";

/**
 * The geometry half of the ER layout: where each attribute ellipse goes round
 * its owner. It is the half with rules a person would state -- in order,
 * clockwise from the top, clear of the owner, clear of each other, off the
 * relationship lines -- so each rule is a test.
 */

const petal = (id: string, width = 60): Petal => ({ id, width, height: 26 });
const OWNER = { width: 120, height: 44 };
const TAU = 2 * Math.PI;

function distance(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function angleGap(a: number, b: number) {
  const d = Math.abs(a - b) % TAU;
  return d > Math.PI ? TAU - d : d;
}

describe("petalAngles", () => {
  it("starts at the top and goes clockwise when nothing is in the way", () => {
    // y grows downwards on screen, so -π/2 is up and +π/2 is down.
    const angles = petalAngles(4, []);
    expect(angles[0]).toBeCloseTo(-Math.PI / 2);
    expect(angles[1]).toBeCloseTo(0); // right
    expect(angles[2]).toBeCloseTo(Math.PI / 2); // down
    expect(angles[3]).toBeCloseTo(Math.PI); // left
  });

  it("spaces them evenly", () => {
    const angles = petalAngles(5, [0.3]);
    for (let i = 1; i < angles.length; i += 1) {
      expect(angles[i] - angles[i - 1]).toBeCloseTo(TAU / 5);
    }
  });

  it("turns the ring off a relationship line that would run under an ellipse", () => {
    // A line straight up, where the first ellipse would sit. An ellipse on a
    // line reads as the line's label.
    const up = -Math.PI / 2;
    const angles = petalAngles(4, [up]);
    const nearest = Math.min(...angles.map((angle) => angleGap(angle, up)));
    // Four ellipses leave 90° gaps; the best turn splits one around the line.
    expect(nearest).toBeCloseTo(Math.PI / 4, 1);
  });

  it("keeps the turn under one step, so the first ellipse still leads from the top", () => {
    const step = TAU / 6;
    const angles = petalAngles(6, [-Math.PI / 2 + 0.01, 1.2, 2.9]);
    expect(angles[0]).toBeGreaterThanOrEqual(-Math.PI / 2 - 1e-9);
    expect(angles[0]).toBeLessThan(-Math.PI / 2 + step);
  });

  it("gives nothing for no ellipses", () => {
    expect(petalAngles(0, [1])).toEqual([]);
  });
});

describe("ringRadius", () => {
  it("clears the owner even with only one or two ellipses", () => {
    const radius = ringRadius(OWNER, [petal("a")]);
    // Half the owner's widest side, half the ellipse, and a gap.
    expect(radius).toBeGreaterThan(OWNER.width / 2 + 30);
  });

  it("grows with the number of ellipses so neighbours do not overlap", () => {
    const few = ringRadius(OWNER, Array.from({ length: 4 }, (_, i) => petal(`p${i}`)));
    const many = ringRadius(OWNER, Array.from({ length: 20 }, (_, i) => petal(`p${i}`)));
    expect(many).toBeGreaterThan(few);
  });

  it("is zero with nothing to place", () => {
    expect(ringRadius(OWNER, [])).toBe(0);
  });
});

describe("placePetals", () => {
  const petals = Array.from({ length: 8 }, (_, i) => petal(`p${i}`, 70));
  const center = { x: 500, y: 300 };
  const placed = placePetals(center, OWNER, petals, []);

  it("places every ellipse, in order, at the same distance from the owner", () => {
    expect([...placed.keys()]).toEqual(petals.map((p) => p.id));
    const radius = ringRadius(OWNER, petals);
    for (const point of placed.values()) {
      expect(distance(point, center)).toBeCloseTo(radius);
    }
  });

  it("puts the first one directly above the owner", () => {
    const first = placed.get("p0")!;
    expect(first.x).toBeCloseTo(center.x);
    expect(first.y).toBeLessThan(center.y);
  });

  it("keeps neighbouring ellipses from overlapping", () => {
    const points = petals.map((p) => placed.get(p.id)!);
    for (let i = 0; i < points.length; i += 1) {
      const next = points[(i + 1) % points.length];
      // Centre to centre at least one ellipse width apart, which is the
      // widest they can be side by side.
      expect(distance(points[i], next)).toBeGreaterThanOrEqual(70 - 1e-6);
    }
  });
});

describe("footprint", () => {
  it("is the owner alone when it has no ellipses", () => {
    expect(footprint(OWNER, [])).toBe(OWNER.width);
  });

  it("covers the whole ring, ellipses included", () => {
    const petals = [petal("a", 80), petal("b", 40)];
    expect(footprint(OWNER, petals)).toBeCloseTo(2 * ringRadius(OWNER, petals) + 80);
  });
});
