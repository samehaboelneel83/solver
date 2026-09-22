// Against a REAL headless cytoscape (GraphEditor.test.tsx mocks the library),
// so the collection calls these helpers make are the library's own.
// `layout: preset` matters: without it headless cytoscape ignores the
// positions given and stacks every node on one point.
import cytoscape from "cytoscape";
import { describe, expect, it } from "vitest";
import { fitReadably, packLooseNodes, shapeMismatch } from "./GraphEditor";

type Spec = cytoscape.ElementDefinition[];

function make(elements: Spec, size?: { w: number; h: number }) {
  const cy = cytoscape({
    headless: true,
    layout: { name: "preset" },
    styleEnabled: true,
    style: [{ selector: "node", style: { width: 60, height: 80 } }],
    elements,
  });
  // Headless cytoscape has no canvas, so no size; give it one.
  if (size) Object.assign(cy, { width: () => size.w, height: () => size.h });
  return cy;
}

describe("packLooseNodes", () => {
  it("moves unconnected top-level nodes into rows under the drawing", () => {
    const cy = make([
      { data: { id: "a" }, position: { x: 0, y: 0 } },
      { data: { id: "b" }, position: { x: 200, y: 0 } },
      { data: { id: "ab", source: "a", target: "b" } },
      { data: { id: "box" }, position: { x: 400, y: 0 } },
      { data: { id: "inside", parent: "box" }, position: { x: 400, y: 0 } },
      // Fourteen loose nodes, stacked in one column the way ELK leaves them.
      ...Array.from({ length: 14 }, (_, i) => ({ data: { id: `l${i}` }, position: { x: -300, y: i * 120 } })),
    ], { w: 1200, h: 800 });
    const inside = { ...cy.$id("inside").position() };
    packLooseNodes(cy);
    const drawingBottom = cy.$id("a").union(cy.$id("b")).union(cy.$id("box")).boundingBox({}).y2;
    const loose = cy.nodes().filter((n) => n.id().startsWith("l")) as cytoscape.NodeCollection;
    loose.forEach((n) => expect(n.boundingBox({}).y1).toBeGreaterThan(drawingBottom));
    // Rows, not a column.
    expect(new Set(loose.map((n) => n.position().y)).size).toBeLessThan(14);
    // A node inside a hierarchy box stays where the box put it, and a
    // connected node is not touched.
    expect(cy.$id("inside").position()).toEqual(inside);
    expect(cy.$id("a").position()).toEqual({ x: 0, y: 0 });
  });

  it("does nothing when every node is connected", () => {
    const cy = make([
      { data: { id: "a" }, position: { x: 1, y: 2 } },
      { data: { id: "b" }, position: { x: 3, y: 4 } },
      { data: { id: "ab", source: "a", target: "b" } },
    ]);
    packLooseNodes(cy);
    expect(cy.$id("a").position()).toEqual({ x: 1, y: 2 });
  });
});

describe("shapeMismatch", () => {
  const line = (n: number, dx: number, dy: number) =>
    make(Array.from({ length: n }, (_, i) => ({ data: { id: `n${i}` }, position: { x: i * dx, y: i * dy } })), {
      w: 1200,
      h: 800,
    });

  it("is true for a tall, narrow drawing on a wide canvas", () => {
    expect(shapeMismatch(line(10, 0, 150))).toBe(true);
  });
  it("is false for a drawing shaped like the canvas", () => {
    expect(shapeMismatch(line(10, 120, 80))).toBe(false);
  });
  it("is false for a single node", () => {
    expect(shapeMismatch(line(1, 0, 0))).toBe(false);
  });
});

describe("fitReadably", () => {
  it("never fits a tiny graph past 1.25x", () => {
    const cy = make([{ data: { id: "a" }, position: { x: 0, y: 0 } }], { w: 1200, h: 800 });
    fitReadably(cy);
    expect(cy.zoom()).toBeLessThanOrEqual(1.25);
  });
});
