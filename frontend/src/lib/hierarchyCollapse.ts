import type { GraphNode, GraphResponse } from "../types/graph";

/**
 * Who sits under a compound parent, at every generation.
 *
 * The canvas nests by `node.parent`. Collapsing a parent has to hide the
 * whole subtree -- a first-generation-only walk would leave grandchildren
 * drawn as orphans once their parent vanished.
 */
export function descendantIds(nodes: GraphNode[], ancestorId: string): string[] {
  const children = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.parent === null) continue;
    const list = children.get(node.parent) ?? [];
    list.push(node.id);
    children.set(node.parent, list);
  }
  const out: string[] = [];
  const stack = [...(children.get(ancestorId) ?? [])];
  while (stack.length > 0) {
    const id = stack.pop()!;
    out.push(id);
    stack.push(...(children.get(id) ?? []));
  }
  return out;
}

/** Every node that is someone's parent -- the ones Collapse all names. */
export function parentIds(nodes: GraphNode[]): string[] {
  const ids = new Set<string>();
  for (const node of nodes) {
    if (node.parent !== null) ids.add(node.parent);
  }
  return [...ids];
}

/** Nodes that must not be drawn because an ancestor is collapsed. */
export function hiddenByCollapse(nodes: GraphNode[], collapsedIds: ReadonlySet<string>): Set<string> {
  const hidden = new Set<string>();
  for (const id of collapsedIds) {
    for (const descendant of descendantIds(nodes, id)) {
      hidden.add(descendant);
    }
  }
  return hidden;
}

export function collapsedLabel(label: string, hiddenCount: number): string {
  return hiddenCount > 0 ? `${label} · ${hiddenCount} hidden` : label;
}

/**
 * The payload `applyGraphToCy` should see: descendants of a collapsed
 * parent are gone, so the parent is no longer a compound box, and any
 * edge that touched a hidden end is gone with it.
 *
 * A collapsed parent's label names how many nodes it is sitting on, using
 * the FULL tree -- a count from the already-filtered nodes would drop
 * grandchildren that this parent's collapse hid via a child.
 */
export function collapseGraph(graph: GraphResponse, collapsedIds: ReadonlySet<string>): GraphResponse {
  if (collapsedIds.size === 0) return graph;
  const hidden = hiddenByCollapse(graph.nodes, collapsedIds);
  return {
    ...graph,
    nodes: graph.nodes
      .filter((node) => !hidden.has(node.id))
      .map((node) => {
        if (!collapsedIds.has(node.id)) return node;
        return { ...node, label: collapsedLabel(node.label, descendantIds(graph.nodes, node.id).length) };
      }),
    edges: graph.edges.filter((edge) => !hidden.has(edge.source) && !hidden.has(edge.target)),
  };
}
