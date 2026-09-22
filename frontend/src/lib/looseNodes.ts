/**
 * Where the Graph View puts entities that have no relationships.
 *
 * ELK's layered layout stacks every unconnected node in one column beside the
 * drawing, so a domain with fourteen days and shifts and no edges between them
 * becomes a strip 1,700 px tall, and "fit" shrinks the whole graph until the
 * names cannot be read. Laid out here instead: in rows under the connected
 * drawing, as wide as it is (or, with nothing connected, a grid shaped like
 * the screen).
 *
 * Pure, so it can be tested without a canvas. Sizes are each node's box
 * INCLUDING its label, and `dx`/`dy` is how far the node's own position sits
 * from that box's centre -- a Graph View name is drawn above the picture, so
 * the box is not centred on the node.
 */

export type LooseNode = { id: string; w: number; h: number; dx: number; dy: number };
export type Box = { x1: number; y1: number; x2: number; y2: number };

const GAP = 32;

export function packLoose(
  connected: Box | null,
  loose: LooseNode[],
  /** Width over height of the canvas, used when nothing is connected. */
  aspect: number
): Record<string, { x: number; y: number }> {
  const placed: Record<string, { x: number; y: number }> = {};
  if (loose.length === 0) return placed;

  // A uniform grid: tidier to read than a ragged packing, and it cannot
  // overlap by construction.
  const cellW = Math.max(...loose.map((n) => n.w)) + GAP;
  const cellH = Math.max(...loose.map((n) => n.h)) + GAP;
  const connectedW = connected ? connected.x2 - connected.x1 : 0;
  const byAspect = Math.ceil(Math.sqrt((loose.length * Math.max(aspect, 0.5) * cellH) / cellW));
  const byDrawing = Math.floor(connectedW / cellW);
  const columns = Math.max(1, Math.min(loose.length, Math.max(byDrawing, byAspect)));

  const left = connected ? connected.x1 : 0;
  const top = connected ? connected.y2 + GAP * 2 : 0;
  loose.forEach((node, i) => {
    const centreX = left + (i % columns) * cellW + cellW / 2;
    const centreY = top + Math.floor(i / columns) * cellH + cellH / 2;
    // A fresh object per node: cytoscape keeps a position by reference.
    placed[node.id] = { x: centreX + node.dx, y: centreY + node.dy };
  });
  return placed;
}
