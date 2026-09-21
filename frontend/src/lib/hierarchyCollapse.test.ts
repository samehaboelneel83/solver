import { describe, expect, it } from "vitest";
import type { GraphNode, GraphResponse } from "../types/graph";
import {
  collapsedLabel,
  collapseGraph,
  descendantIds,
  hiddenByCollapse,
  parentIds,
} from "./hierarchyCollapse";

const nodes: GraphNode[] = [
  { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
  { id: "2", type: "unit", label: "ops", parent: "1", attributes: {} },
  { id: "3", type: "employee", label: "ahmed", parent: "2", attributes: {} },
  { id: "4", type: "unit", label: "east", parent: "1", attributes: {} },
];

describe("descendantIds", () => {
  it("walks every generation, not just the first", () => {
    expect(descendantIds(nodes, "1").sort()).toEqual(["2", "3", "4"]);
    expect(descendantIds(nodes, "2")).toEqual(["3"]);
    expect(descendantIds(nodes, "3")).toEqual([]);
  });
});

describe("parentIds", () => {
  it("names every node that currently has someone under it", () => {
    expect(parentIds(nodes).sort()).toEqual(["1", "2"]);
  });
});

describe("hiddenByCollapse", () => {
  it("hides the whole subtree of each collapsed parent", () => {
    expect([...hiddenByCollapse(nodes, new Set(["1"]))].sort()).toEqual(["2", "3", "4"]);
    expect([...hiddenByCollapse(nodes, new Set(["2"]))]).toEqual(["3"]);
  });

  it("does not hide the collapsed parent itself", () => {
    expect(hiddenByCollapse(nodes, new Set(["1"])).has("1")).toBe(false);
  });
});

describe("collapsedLabel", () => {
  it("says how many are sitting under the parent", () => {
    expect(collapsedLabel("hq", 3)).toBe("hq · 3 hidden");
    expect(collapsedLabel("hq", 0)).toBe("hq");
  });
});

describe("collapseGraph", () => {
  const graph: GraphResponse = {
    nodes,
    edges: [
      { id: "e1", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} },
      { id: "e2", source: "2", target: "3", type: "reports_to", label: "reports_to", attributes: {} },
      { id: "e3", source: "1", target: "4", type: "reports_to", label: "reports_to", attributes: {} },
    ],
    entity_types: [],
    relationship_types: [],
    hierarchies: [],
    attribute_definitions: [],
  };

  it("leaves the payload alone when nothing is collapsed", () => {
    expect(collapseGraph(graph, new Set())).toBe(graph);
  });

  it("drops hidden nodes and any edge that touched them, and marks the parent", () => {
    const drawn = collapseGraph(graph, new Set(["1"]));
    expect(drawn.nodes.map((n) => n.id)).toEqual(["1"]);
    expect(drawn.nodes[0].label).toBe("hq · 3 hidden");
    expect(drawn.edges).toEqual([]);
  });

  it("keeps an edge whose two ends are still drawn", () => {
    const drawn = collapseGraph(graph, new Set(["2"]));
    expect(drawn.nodes.map((n) => n.id).sort()).toEqual(["1", "2", "4"]);
    expect(drawn.edges.map((e) => e.id).sort()).toEqual(["e1", "e3"]);
    expect(drawn.nodes.find((n) => n.id === "2")?.label).toBe("ops · 1 hidden");
    expect(drawn.nodes.find((n) => n.id === "1")?.label).toBe("hq");
  });
});
