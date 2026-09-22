/**
 * Where each part of a model sits, for the drawing styles that place nodes
 * themselves (Rete.js, React Flow). Every style reads left to right in the
 * same order the Cytoscape view does:
 *
 *     sets  ->  variables and parameters  ->  rules  ->  objective
 *
 * The columns are fixed by what a node is, not found by a layout engine: a
 * set nothing reads would otherwise drift into whichever column had room.
 * Within a column, nodes are ordered by where their inputs sit (the
 * barycentre heuristic), which keeps edges short and mostly uncrossed, and
 * each column is centred on the tallest one.
 */

import type { GraphResponse } from "../types/graph";
import type { ModelPart } from "./modelGraph";

export type Box = { x: number; y: number; width: number; height: number };

const COLUMN: Record<ModelPart, number> = { sets: 0, variables: 1, parameters: 1, rules: 2, objective: 3 };

export function layoutModel(
  graph: GraphResponse,
  size: (id: string) => { width: number; height: number },
  { columnGap = 110, rowGap = 28 }: { columnGap?: number; rowGap?: number } = {}
): Map<string, Box> {
  const columns: string[][] = [[], [], [], []];
  for (const node of graph.nodes) columns[COLUMN[node.type as ModelPart] ?? 1].push(node.id);

  const inputs = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (!inputs.has(edge.target)) inputs.set(edge.target, []);
    inputs.get(edge.target)!.push(edge.source);
  }

  // Order each column by the mean rank of its inputs in earlier columns;
  // a node with none keeps its place, after those that have some.
  const rank = new Map<string, number>();
  columns.forEach((column, c) => {
    if (c > 0) {
      const score = (id: string) => {
        const ranks = (inputs.get(id) ?? []).map((source) => rank.get(source)).filter((r) => r !== undefined);
        return ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : Number.POSITIVE_INFINITY;
      };
      column.sort((a, b) => score(a) - score(b));
    }
    column.forEach((id, index) => rank.set(id, index));
  });

  const heights = columns.map((column) =>
    column.reduce((total, id) => total + size(id).height, 0) + Math.max(0, column.length - 1) * rowGap
  );
  const tallest = Math.max(0, ...heights);

  const boxes = new Map<string, Box>();
  let x = 0;
  columns.forEach((column, c) => {
    const width = Math.max(0, ...column.map((id) => size(id).width));
    let y = (tallest - heights[c]) / 2;
    for (const id of column) {
      const { width: w, height: h } = size(id);
      boxes.set(id, { x, y, width: w, height: h });
      y += h + rowGap;
    }
    if (column.length) x += width + columnGap;
  });
  return boxes;
}

/** What each part is called on a card or node header. */
export const PART_TITLE: Record<ModelPart, string> = {
  sets: "Set",
  variables: "Decision",
  parameters: "Data",
  rules: "Rule",
  objective: "Goal",
};
