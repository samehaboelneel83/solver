import type { GraphPalette } from "../../lib/typesGraph";
import type { GraphResponse } from "../../types/graph";

/** The optimization view's drawing styles. `graph` is the Cytoscape canvas. */
export const MODEL_STYLES = ["graph", "blockly", "rete", "flow"] as const;
export type ModelStyle = (typeof MODEL_STYLES)[number];

export const MODEL_STYLE_NAME: Record<ModelStyle, string> = {
  graph: "Graph",
  blockly: "Blockly",
  rete: "Rete.js",
  flow: "React Flow",
};

export const MODEL_STYLE_TITLE: Record<ModelStyle, string> = {
  graph: "The model as a graph: sets, decisions and data flowing into rules and the goal",
  blockly: "The model as blocks: each rule and the goal built from nested blocks, like a program",
  rete: "The model as a node editor: each part a node, wired through its inputs and outputs",
  flow: "The model as a flow chart: cards left to right, from sets to the goal",
};

/** What every alternative style draws from: the same graph the Cytoscape
 * view draws, its colours, and the IR it was built from. */
export type ModelStyleProps = {
  graph: GraphResponse;
  palette: GraphPalette;
  ir: Record<string, unknown> | null | undefined;
  title?: string;
  onSelect: (nodeId: string) => void;
};
