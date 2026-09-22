import { describe, expect, it } from "vitest";
import { packLoose, type LooseNode } from "./looseNodes";

const node = (id: string, w = 60, h = 80): LooseNode => ({ id, w, h, dx: 0, dy: 0 });
const boxes = (placed: Record<string, { x: number; y: number }>, nodes: LooseNode[]) =>
  nodes.map((n) => ({
    id: n.id,
    x1: placed[n.id].x - n.w / 2,
    x2: placed[n.id].x + n.w / 2,
    y1: placed[n.id].y - n.h / 2,
    y2: placed[n.id].y + n.h / 2,
  }));

describe("packLoose", () => {
  it("places nothing when there is nothing loose", () => {
    expect(packLoose({ x1: 0, y1: 0, x2: 100, y2: 100 }, [], 1.5)).toEqual({});
  });

  it("puts loose nodes in rows below the connected drawing, never on it", () => {
    const loose = Array.from({ length: 14 }, (_, i) => node(`n${i}`));
    const placed = packLoose({ x1: 0, y1: 0, x2: 400, y2: 300 }, loose, 1.5);
    for (const b of boxes(placed, loose)) expect(b.y1).toBeGreaterThan(300);
    // Rows, not a column: more than one node per row.
    const rows = new Set(Object.values(placed).map((p) => p.y));
    expect(rows.size).toBeLessThan(loose.length);
    expect(rows.size).toBeGreaterThan(1);
  });

  it("never overlaps two loose nodes", () => {
    const loose = [node("a", 60, 80), node("b", 140, 80), node("c", 60, 40), node("d", 90, 90), node("e", 60, 80)];
    const b = boxes(packLoose(null, loose, 1.5), loose);
    for (let i = 0; i < b.length; i++)
      for (let j = i + 1; j < b.length; j++) {
        const overlap = b[i].x1 < b[j].x2 && b[j].x1 < b[i].x2 && b[i].y1 < b[j].y2 && b[j].y1 < b[i].y2;
        expect(overlap, `${b[i].id}/${b[j].id}`).toBe(false);
      }
  });

  it("with nothing connected, makes a roughly screen-shaped grid", () => {
    const loose = Array.from({ length: 24 }, (_, i) => node(`n${i}`));
    const b = boxes(packLoose(null, loose, 1.5), loose);
    const w = Math.max(...b.map((x) => x.x2)) - Math.min(...b.map((x) => x.x1));
    const h = Math.max(...b.map((x) => x.y2)) - Math.min(...b.map((x) => x.y1));
    expect(w / h).toBeGreaterThan(0.8);
    expect(w / h).toBeLessThan(3);
  });

  it("accounts for a label that sits off-centre (dx, dy)", () => {
    // The box is 40 px higher than the node's centre: its label is above.
    const placed = packLoose({ x1: 0, y1: 0, x2: 100, y2: 100 }, [{ id: "a", w: 60, h: 100, dx: 0, dy: 20 }], 1.5);
    // Box top = centre - dy - h/2 must clear the drawing.
    expect(placed.a.y - 20 - 50).toBeGreaterThan(100);
  });

  it("returns a fresh object per node (cytoscape keeps positions by reference)", () => {
    const placed = packLoose(null, [node("a"), node("b")], 1.5);
    expect(placed.a).not.toBe(placed.b);
  });
});
