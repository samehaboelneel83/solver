import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GeometryPreview from "./GeometryPreview";

describe("GeometryPreview", () => {
  it("draws a polygon inside its box, north up", () => {
    const { container } = render(
      <GeometryPreview geometry={{ type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]] }} size={100} />
    );
    expect(screen.getByRole("img", { name: "Polygon, 5 positions" })).toBeInTheDocument();
    const ys = [...container.querySelector("path")!.getAttribute("d")!.matchAll(/[ML][\d.]+,([\d.]+)/g)].map((m) => Number(m[1]));
    // Latitude 0 (south) is drawn lower than latitude 1 (north).
    expect(ys[0]).toBeGreaterThan(ys[3]);
    for (const v of ys) {
      expect(v).toBeGreaterThanOrEqual(4);
      expect(v).toBeLessThanOrEqual(96);
    }
  });

  it("draws a point as a dot", () => {
    const { container } = render(<GeometryPreview geometry={{ type: "Point", coordinates: [31.2, 30] }} />);
    expect(container.querySelector("circle")).not.toBeNull();
  });

  it("says what it cannot draw instead of drawing nothing", () => {
    render(<GeometryPreview geometry={"not geojson"} size={80} />);
    expect(screen.getByText("No shape to draw")).toBeInTheDocument();
  });
});
