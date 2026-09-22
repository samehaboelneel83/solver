/**
 * A model graph as nodes with named inputs and one output: the shape a
 * node editor (Rete.js) and a flow chart (React Flow) both draw.
 *
 * Built from `buildModelView`'s graph, so every style shows the same parts
 * with the same ids. Each edge into a node is one input, labelled with what
 * flows in -- the variable or parameter, or the set and any attribute of it
 * read as a number (`employee · hours_per_week`). A node that feeds anything
 * has one output, named for what it supplies.
 */

import type { GraphResponse } from "../types/graph";
import { modelDetails, type ModelPart } from "./modelGraph";

export type NodeSpec = {
  id: string;
  part: ModelPart;
  name: string;
  /** The node's other label line: "binary [employee, day, shift]", "must hold". */
  subtitle: string;
  inputs: { key: string; label: string; from: string }[];
  output: string | null;
  summary: string;
};

const OUTPUT: Record<ModelPart, string> = {
  sets: "members",
  variables: "decision",
  parameters: "value",
  rules: "penalty",
  objective: "",
};

// The one fact that says most about each part, from its side-panel details.
const SUMMARY: Record<ModelPart, string[]> = {
  sets: ["Ranges over"],
  variables: ["Values"],
  parameters: ["Indexed by"],
  rules: ["Rule"],
  objective: ["Sense"],
};

export function reteNodes(graph: GraphResponse): NodeSpec[] {
  const nameOf = new Map(graph.nodes.map((node) => [node.id, node.label.split("\n")[0]]));
  const feeds = new Set(graph.edges.map((edge) => edge.source));
  return graph.nodes.map((node) => {
    const part = node.type as ModelPart;
    const [name, ...rest] = node.label.split("\n");
    const details = new Map(modelDetails(node) ?? []);
    const inputs = graph.edges
      .filter((edge) => edge.target === node.id)
      .map((edge, index) => ({
        key: `in${index}`,
        from: edge.source,
        label: `${nameOf.get(edge.source) ?? edge.source}${edge.label ? ` · ${edge.label}` : ""}`,
      }));
    return {
      id: node.id,
      part,
      name,
      subtitle: rest.join(" "),
      inputs,
      output: feeds.has(node.id) ? OUTPUT[part] || "value" : null,
      summary: SUMMARY[part].map((key) => details.get(key)).filter(Boolean).join(" · "),
    };
  });
}
