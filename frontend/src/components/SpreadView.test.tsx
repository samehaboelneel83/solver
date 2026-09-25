import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SpreadView, { binsOf } from "./SpreadView";

describe("the spread across futures (queue R17b)", () => {
  it("bins the costs from the least to the most, every future in one bin", () => {
    const bins = binsOf([1, 2, 2, 3, 10], 3);
    expect(bins.map((b) => b.n)).toEqual([4, 0, 1]);
    expect(binsOf([5, 5])).toEqual([{ from: 5, to: 5, n: 2 }]);
  });

  it("draws the futures with the mean and its interval", () => {
    render(<SpreadView costs={[100, 120, 140]} mean={120} ci95={22.6} unmet={1} />);
    expect(screen.getByRole("img", { name: "Spread of 3 futures from 100 to 140" })).toBeInTheDocument();
    expect(screen.getByText("mean 120")).toBeInTheDocument();
    expect(screen.getByText(/1 it cannot meet are not drawn/)).toBeInTheDocument();
  });
});
