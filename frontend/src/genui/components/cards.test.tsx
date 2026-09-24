import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Curve } from "./cards";

describe("the progress curve", () => {
  it("draws both series inside its box, the lowest value included", () => {
    const { container } = render(
      <Curve history={[
        { elapsed: 0.2, objective: 11300, bound: 11400 },
        { elapsed: 0.5, objective: 11347, bound: 11376 },
        { elapsed: 0.7, objective: 11347, bound: 11376 },
      ]} />
    );
    expect(screen.getByRole("img", { name: "best answer and bound over time" })).toBeInTheDocument();
    const d = (series: string) => container.querySelector(`[data-series="${series}"]`)!.getAttribute("d")!;
    // The y of each move (`M x,y`) and each vertical step (`V y`).
    const ys = (path: string) =>
      [...path.matchAll(/M[\d.]+,(-?[\d.]+)|V(-?[\d.]+)/g)].map((m) => Number(m[1] ?? m[2]));
    for (const series of ["objective", "bound"]) {
      expect(d(series)).toMatch(/^M/);
      // Within the padded box: never on or past an edge of 0..96.
      const heights = ys(d(series));
      expect(heights.length).toBeGreaterThan(0);
      for (const y of heights) {
        expect(y).toBeGreaterThanOrEqual(8);
        expect(y).toBeLessThanOrEqual(88);
      }
    }
    expect(screen.getByText("11,400")).toBeInTheDocument();
    expect(screen.getByText("11,300")).toBeInTheDocument();
  });

  it("draws a flat run of one value rather than dividing by nothing", () => {
    const { container } = render(<Curve history={[{ elapsed: 1, objective: 5, bound: 5 }, { elapsed: 2, objective: 5, bound: 5 }]} />);
    expect(container.querySelector('[data-series="objective"]')!.getAttribute("d")).not.toMatch(/NaN|Infinity/);
  });

  it("scales to the run after its first answer and says the opening bound is off the scale", () => {
    render(
      <Curve history={[
        { elapsed: 0.01, objective: null, bound: 21485 },
        { elapsed: 0.2, objective: 11300, bound: 11400 },
        { elapsed: 30, objective: 11355, bound: 11376 },
      ]} />
    );
    expect(screen.getByText("11,400")).toBeInTheDocument();
    expect(screen.queryByText("21,485")).not.toBeInTheDocument();
    expect(screen.getByText("the opening bound, before the first answer, is off the scale")).toBeInTheDocument();
  });
});
