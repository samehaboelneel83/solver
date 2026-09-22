/**
 * Laying out the types view as an ER diagram.
 *
 * A general-purpose layout does this badly. ELK's layered algorithm (what the
 * objects view uses) puts every node in rows, so an entity's ellipses end up
 * in a column somewhere to its right; a force layout does better but puts
 * them in whatever order the simulation settles, which throws away the order
 * someone chose for them (migration 0027).
 *
 * So it is done in two steps, which is also how a person draws one:
 *
 * 1. **The skeleton** -- the rectangles, the diamonds and the lines between
 *    them -- is laid out by ELK's layered algorithm, with every node
 *    temporarily as large as the ring of ellipses it will carry. That
 *    reserves the room, so two entities are never placed close enough for
 *    their attributes to collide.
 * 2. **The petals.** Each owner's ellipses go on a circle around it, evenly
 *    spaced, in their sort order clockwise from the top, and the whole ring
 *    is turned to keep the ellipses off the owner's relationship lines --
 *    an ellipse sitting on a line reads as the line's label.
 *
 * Step 2 is plain geometry and exported on its own, so it is tested without
 * a canvas.
 */

import type { Core, NodeSingular } from "cytoscape";

export type Point = { x: number; y: number };
export type Petal = { id: string; width: number; height: number };

/** Room between two neighbouring ellipses on a ring. */
const PETAL_GAP = 14;
/** Room between an owner's edge and the nearest point of an ellipse. */
const OWNER_CLEARANCE = 18;
/** How far apart two neighbouring skeleton footprints are kept. */
const SKELETON_GAP = 40;
/** The zoom range a fresh layout settles in -- see `runErLayout`. */
const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.1;

/**
 * The radius of an owner's ring of ellipses.
 *
 * Large enough for two things at once: every ellipse fits round the
 * circumference with a gap between neighbours, and no ellipse overlaps the
 * owner itself -- a wide rectangle needs a wider ring even for two
 * attributes.
 */
export function ringRadius(owner: { width: number; height: number }, petals: readonly Petal[]): number {
  if (petals.length === 0) return 0;
  const widest = Math.max(...petals.map((p) => p.width));
  const circumference = petals.reduce((sum, p) => sum + p.width + PETAL_GAP, 0);
  const clearOwner = Math.max(owner.width, owner.height) / 2 + widest / 2 + OWNER_CLEARANCE;
  return Math.max(circumference / (2 * Math.PI), clearOwner);
}

/** The smallest angle between two directions, in radians. */
function angularDistance(a: number, b: number): number {
  const d = Math.abs(a - b) % (2 * Math.PI);
  return d > Math.PI ? 2 * Math.PI - d : d;
}

/**
 * The angle of each of `count` ellipses, in order, clockwise from the top.
 *
 * Evenly spaced, then the whole ring is turned by the offset that keeps the
 * nearest ellipse furthest from any of `avoid` -- the directions of the
 * owner's relationship lines. The turn is bounded by one step, so the first
 * ellipse (the key, for an entity) stays at or just after the top and the
 * order still reads round from there.
 *
 * Screen coordinates: y grows downwards, so -π/2 is up and a growing angle
 * turns clockwise.
 */
export function petalAngles(count: number, avoid: readonly number[]): number[] {
  if (count === 0) return [];
  const step = (2 * Math.PI) / count;
  const at = (offset: number) => Array.from({ length: count }, (_, i) => -Math.PI / 2 + offset + i * step);
  if (avoid.length === 0) return at(0);

  const CANDIDATES = 24;
  let best = 0;
  let bestScore = -1;
  for (let k = 0; k < CANDIDATES; k += 1) {
    const offset = (step * k) / CANDIDATES;
    const score = Math.min(...at(offset).flatMap((angle) => avoid.map((line) => angularDistance(angle, line))));
    // Strictly better only, so ties keep the smaller turn and the ring
    // stays as close to "first at the top" as the lines allow.
    if (score > bestScore + 1e-9) {
      bestScore = score;
      best = offset;
    }
  }
  return at(best);
}

/** Where each ellipse goes: on the ring round `center`, at its angle. */
export function placePetals(
  center: Point,
  owner: { width: number; height: number },
  petals: readonly Petal[],
  avoid: readonly number[]
): Map<string, Point> {
  const radius = ringRadius(owner, petals);
  const angles = petalAngles(petals.length, avoid);
  const placed = new Map<string, Point>();
  petals.forEach((petal, i) => {
    placed.set(petal.id, {
      x: center.x + radius * Math.cos(angles[i]),
      y: center.y + radius * Math.sin(angles[i]),
    });
  });
  return placed;
}

/** The whole footprint an owner needs: itself and its ring, as a square. */
export function footprint(owner: { width: number; height: number }, petals: readonly Petal[]): number {
  if (petals.length === 0) return Math.max(owner.width, owner.height);
  const radius = ringRadius(owner, petals);
  const widest = Math.max(...petals.map((p) => p.width));
  return 2 * radius + widest;
}

// -- the cytoscape half --------------------------------------------------------

function sizeOf(node: NodeSingular): { width: number; height: number } {
  return { width: node.width(), height: node.height() };
}

/** An owner's showing ellipses, in their chosen order. Sorted by the `seq`
 * `buildTypesView` stamps on each rather than by collection order: cytoscape
 * keeps elements in insertion order, which an incremental update does not
 * promise to keep equal to the chosen one. */
function petalsOf(owner: NodeSingular): Petal[] {
  const found: { seq: number; petal: Petal }[] = [];
  owner.connectedEdges('[er = "attribute-link"]').forEach((edge) => {
    const petal = edge.target();
    if (petal.id() === owner.id() || petal.style("display") === "none") return;
    found.push({
      seq: Number(petal.data("seq") ?? 0),
      petal: { id: petal.id(), width: petal.width(), height: petal.height() },
    });
  });
  return found.sort((a, b) => a.seq - b.seq).map((entry) => entry.petal);
}

/**
 * Lay the ER drawing out. Resolves once every node has its final position.
 *
 * Positions are always written as fresh objects: cytoscape keeps a node's
 * position by reference, and two nodes handed one object would move as one.
 */
export function runErLayout(cy: Core): Promise<void> {
  const skeleton = cy.nodes('[er = "entity"], [er = "relationship"]');
  const connectors = cy.edges('[er = "connector"]');

  // Each owner's petals and footprint, measured before anything moves.
  const petals = new Map<string, Petal[]>();
  const size = new Map<string, number>();
  skeleton.forEach((node) => {
    const list = petalsOf(node);
    petals.set(node.id(), list);
    size.set(node.id(), footprint(sizeOf(node), list));
  });

  // Laid out at the size of its ring, so the ring's room is reserved. ELK's
  // layered algorithm is deterministic, so the same schema lays out the same
  // way every time without a seeded starting position.
  cy.batch(() => {
    skeleton.forEach((node) => {
      const side = size.get(node.id()) ?? 60;
      node.style({ width: side, height: side });
    });
  });

  return new Promise<void>((resolve) => {
    const finish = () => {
      cy.batch(() => {
        skeleton.removeStyle("width height");
        skeleton.forEach((owner) => {
          const center = owner.position();
          const avoid: number[] = [];
          connectors.forEach((edge) => {
            if (edge.style("display") === "none") return;
            const other =
              edge.source().id() === owner.id()
                ? edge.target()
                : edge.target().id() === owner.id()
                  ? edge.source()
                  : null;
            if (!other || other.id() === owner.id()) return;
            const at = other.position();
            avoid.push(Math.atan2(at.y - center.y, at.x - center.x));
          });
          const placed = placePetals(
            { x: center.x, y: center.y },
            sizeOf(owner),
            petals.get(owner.id()) ?? [],
            avoid
          );
          placed.forEach((point, id) => {
            cy.getElementById(id).position({ x: point.x, y: point.y });
          });
        });
      });
      cy.fit(undefined, 30);
      // A small schema fitted to a large canvas would be drawn at several
      // times its size, and a large one shrunk until nothing reads. Keep the
      // zoom where the text stays legible; pan and zoom are still the user's.
      const zoom = cy.zoom();
      const clamped = Math.min(Math.max(zoom, MIN_ZOOM), MAX_ZOOM);
      if (clamped !== zoom) {
        cy.zoom(clamped);
        cy.center();
      }
      resolve();
    };

    // ELK's layered algorithm over the footprints. Measured on the Workforce
    // schema against cytoscape's force-directed `cose`: cose left about 90%
    // of its bounding box empty (it packs disconnected types badly and does
    // not pull connected footprints together), layered filled about half of
    // it with no overlaps, in a near-square that suits the canvas. And
    // because each relationship's second line is drawn FROM its diamond
    // (see `buildTypesView`), layering puts the diamond between the two
    // types it relates rather than below both.
    const layout = skeleton.union(connectors).layout({
      name: "elk",
      animate: false,
      fit: false,
      nodeDimensionsIncludeLabels: false,
      elk: {
        algorithm: "layered",
        // Left to right: a schema reads `employee -- works_in -- unit`, and a
        // canvas is wider than it is tall. Measured on Workforce, DOWN came
        // out twice as tall as wide and could only be shown at 56%; RIGHT
        // fits at about 75%, which is the difference between reading the
        // attribute names and not.
        "elk.direction": "RIGHT",
        // Pack the disconnected types to the canvas's own shape.
        "elk.aspectRatio": Math.max(1, Math.min(3, cy.width() / Math.max(1, cy.height()))),
        "elk.spacing.nodeNode": SKELETON_GAP / 2,
        "elk.layered.spacing.nodeNodeBetweenLayers": SKELETON_GAP / 2,
        "elk.spacing.componentComponent": SKELETON_GAP,
      },
    } as never);
    layout.one("layoutstop", finish);
    layout.run();
  });
}
