import { FormEvent, useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { useCreateEdge, useCreateNode, useGraph } from "../api/graph";
import { formatApiError } from "../api/errors";
import type { GraphEdge, GraphNode, GraphResponse, RelationshipTypeOption } from "../types/graph";
import type { FilterCriteria } from "./FilterBar";

cytoscape.use(elk);
cytoscape.use(edgehandles);

type Selection = { kind: "node" | "edge"; id: string } | null;

type GraphEditorProps = {
  organizationId: string;
  hierarchyId: string | null;
  onHierarchyChange: (id: string | null) => void;
  filter?: FilterCriteria;
  onSelectionChange?: (selection: Selection) => void;
};

const ELK_LAYOUT = {
  name: "elk",
  elk: { algorithm: "layered", "elk.hierarchyHandling": "INCLUDE_CHILDREN" },
} as const;

/**
 * Diffs `graph` against the elements already present in `cy` and applies the
 * minimal set of changes: removes ids no longer present, adds new ones
 * (positioned at the centre of the current viewport), updates `data` on
 * existing ones, and moves nodes whose `parent` changed.
 *
 * `structureChanged` is true only when a node was added/removed or a node's
 * parent changed -- adding/removing an edge, or changing only a label/type,
 * does not warrant a relayout.
 */
export function applyGraphToCy(cy: Core, graph: GraphResponse): { structureChanged: boolean } {
  let structureChanged = false;

  const desiredNodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const desiredEdges = new Map(graph.edges.map((e) => [e.id, e]));

  const existingNodeIds = new Set<string>();
  const existingEdgeIds = new Set<string>();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (cy as any)
    .nodes()
    .forEach((ele: any) => existingNodeIds.add(ele.id()));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (cy as any)
    .edges()
    .forEach((ele: any) => existingEdgeIds.add(ele.id()));

  existingNodeIds.forEach((id) => {
    if (!desiredNodes.has(id)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (cy as any).remove?.((cy as any).getElementById(id));
      structureChanged = true;
    }
  });
  existingEdgeIds.forEach((id) => {
    if (!desiredEdges.has(id)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (cy as any).remove?.((cy as any).getElementById(id));
    }
  });

  const newNodes: GraphNode[] = [];
  desiredNodes.forEach((node, id) => {
    if (existingNodeIds.has(id)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ele = (cy as any).getElementById(id);
      ele.data({ label: node.label, type: node.type });
      const currentParent = ele.data("parent") ?? undefined;
      const desiredParent = node.parent ?? undefined;
      if (currentParent !== desiredParent) {
        ele.move({ parent: desiredParent ?? null });
        structureChanged = true;
      }
    } else {
      newNodes.push(node);
    }
  });

  const newEdges: GraphEdge[] = [];
  desiredEdges.forEach((edge, id) => {
    if (existingEdgeIds.has(id)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ele = (cy as any).getElementById(id);
      ele.data({ label: edge.label, type: edge.type });
    } else {
      newEdges.push(edge);
    }
  });

  if (newNodes.length > 0 || newEdges.length > 0) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const extent = (cy as any).extent?.() ?? { x1: 0, y1: 0, x2: 0, y2: 0 };
    const center = { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 };
    const elementsToAdd = [
      ...newNodes.map((node) => ({
        data: { id: node.id, label: node.label, type: node.type, parent: node.parent ?? undefined },
        position: center,
      })),
      ...newEdges.map((edge) => ({
        data: { id: edge.id, source: edge.source, target: edge.target, label: edge.label, type: edge.type },
      })),
    ];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (cy as any).add?.(elementsToAdd);
    if (newNodes.length > 0) {
      structureChanged = true;
    }
  }

  return { structureChanged };
}

export default function GraphEditor({
  organizationId,
  hierarchyId,
  onHierarchyChange,
  filter,
  onSelectionChange,
}: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ehRef = useRef<any>(null);
  const graphRef = useRef<GraphResponse | null>(null);
  const hasLaidOutRef = useRef(false);

  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [layoutStatus, setLayoutStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading, error: loadError } = useGraph(organizationId, hierarchyId);
  const createNode = useCreateNode(organizationId, hierarchyId);
  const createEdge = useCreateEdge(organizationId, hierarchyId);

  // Create the cytoscape instance exactly once per mount. Data is applied
  // (and the instance kept alive across refetches/mutations) by the effect
  // below, so zoom/pan/dragged positions survive data changes.
  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "#0f172a",
            color: "#0f172a",
            "font-size": "10px",
            width: 30,
            height: 30,
          },
        },
        {
          selector: "$node > node",
          style: {
            "background-color": "#e2e8f0",
            "background-opacity": 0.4,
            "border-width": 1,
            "border-color": "#94a3b8",
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": "9px",
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
        { selector: ".graph-highlighted", style: { "border-width": 3, "border-color": "#2563eb" } },
        { selector: ".graph-dimmed", style: { opacity: 0.25 } },
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const eh = (cy as any).edgehandles({});
    ehRef.current = eh;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", "node", (evt: any) => {
      onSelectionChange?.({ kind: "node", id: evt.target.id() });
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", "edge", (evt: any) => {
      onSelectionChange?.({ kind: "edge", id: evt.target.id() });
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", (evt: any) => {
      if (evt.target === cy) {
        onSelectionChange?.(null);
      }
    });
    cy.on("ehcomplete", (_event: unknown, sourceNode: NodeSingular, targetNode: NodeSingular) => {
      setPendingEdge({ sourceId: sourceNode.id(), targetId: targetNode.id() });
    });

    cyRef.current = cy;

    return () => {
      eh.destroy();
      cy.destroy();
      cyRef.current = null;
      ehRef.current = null;
      hasLaidOutRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) {
      return;
    }
    const { structureChanged } = applyGraphToCy(cy, data);
    graphRef.current = data;
    if (structureChanged || !hasLaidOutRef.current) {
      hasLaidOutRef.current = true;
      startLayout(cy);
    }
  }, [data]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) {
      return;
    }
    const searchLower = (filter?.search ?? "").toLowerCase();
    const selectedTypes = filter?.selectedTypes ?? null;
    const highlightIds = filter?.highlightIds ?? null;

    cy.nodes().forEach((node) => {
      const graphNode = data.nodes.find((n) => n.id === node.id());
      if (!graphNode) {
        return;
      }
      const typeOk = selectedTypes === null || selectedTypes.includes(graphNode.type);
      const searchOk = !searchLower || graphNode.label.toLowerCase().includes(searchLower);
      node.style("display", typeOk && searchOk ? "element" : "none");
    });

    cy.edges().forEach((edge) => {
      const source = cy.getElementById(edge.data("source"));
      const target = cy.getElementById(edge.data("target"));
      const visible = source.style("display") !== "none" && target.style("display") !== "none";
      edge.style("display", visible ? "element" : "none");
    });

    cy.elements().removeClass("graph-highlighted graph-dimmed");
    if (highlightIds) {
      const highlightSet = new Set(highlightIds);
      cy.nodes().forEach((node) => {
        node.addClass(highlightSet.has(node.id()) ? "graph-highlighted" : "graph-dimmed");
      });
    }
  }, [filter, data]);

  function startLayout(cy: Core) {
    const fail = () => {
      setLayoutStatus(null);
      setError("Layout failed");
    };
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const lay: any = cy.layout(ELK_LAYOUT as any);
      lay.on?.("layoutstart", () => setLayoutStatus("Laying out…"));
      lay.on?.("layoutstop", () => setLayoutStatus(null));
      const runResult = lay.run();
      Promise.resolve(runResult).catch(fail);
      lay.promiseOn?.("layoutstop")?.catch(fail);
    } catch {
      fail();
    }
  }

  function runLayout() {
    if (cyRef.current) {
      startLayout(cyRef.current);
    }
  }

  function fit() {
    cyRef.current?.fit();
  }

  function toggleConnect() {
    const cy = cyRef.current;
    const eh = ehRef.current;
    if (!cy || !eh) {
      return;
    }
    const next = !connecting;
    setConnecting(next);
    if (next) {
      eh.enableDrawMode?.();
    } else {
      eh.disableDrawMode?.();
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (cy as any).autoungrabify?.(next);
  }

  function nodeEntityType(entityId: string): string | undefined {
    return data?.nodes.find((n) => n.id === entityId)?.type;
  }

  function entityTypeName(code: string | undefined): string {
    if (!code) {
      return "?";
    }
    return data?.entity_types.find((et) => et.code === code)?.name ?? code;
  }

  function validRelationshipTypesFor(sourceId: string, targetId: string): RelationshipTypeOption[] {
    const sourceType = nodeEntityType(sourceId);
    const targetType = nodeEntityType(targetId);
    return (data?.relationship_types ?? []).filter((rt) => {
      const sourceOk = rt.source_entity_type === null || rt.source_entity_type === sourceType;
      const targetOk = rt.target_entity_type === null || rt.target_entity_type === targetType;
      return sourceOk && targetOk;
    });
  }

  function handleConfirmEdge(relationshipTypeId: string) {
    if (!pendingEdge) {
      return;
    }
    createEdge.mutate(
      {
        relationship_type_id: relationshipTypeId,
        source_entity_id: pendingEdge.sourceId,
        target_entity_id: pendingEdge.targetId,
      },
      { onError: (e) => setError(formatApiError(e)) }
    );
    setPendingEdge(null);
  }

  function handleCreateNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const entityTypeId = String(form.get("entity_type_id") ?? "");
    const name = String(form.get("name") ?? "");
    const code = String(form.get("code") ?? "") || undefined;
    const parentEntityId = String(form.get("parent_entity_id") ?? "") || undefined;
    if (!entityTypeId || !name) {
      return;
    }
    createNode.mutate(
      {
        organization_id: organizationId,
        entity_type_id: entityTypeId,
        name,
        code,
        hierarchy_id: hierarchyId ?? undefined,
        parent_entity_id: parentEntityId,
      },
      { onError: (e) => setError(formatApiError(e)) }
    );
    setShowCreateNode(false);
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => onHierarchyChange(e.target.value || null)}
          data-testid="hierarchy-select"
        >
          <option value="">No hierarchy nesting</option>
          {data?.hierarchies.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <button onClick={runLayout} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Layout
        </button>
        <button onClick={fit} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Fit
        </button>
        <button
          type="button"
          onClick={toggleConnect}
          className={`rounded-md border px-2 py-1 text-sm ${
            connecting ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-300"
          }`}
          data-testid="toggle-connect"
        >
          {connecting ? "Connecting: drag from one node to another" : "Connect"}
        </button>
        <button
          type="button"
          onClick={() => setShowCreateNode((v) => !v)}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
        {layoutStatus && (
          <span data-testid="layout-status" className="text-xs text-slate-400">
            {layoutStatus}
          </span>
        )}
      </div>

      {error && (
        <div
          data-testid="graph-error"
          className="mb-2 flex items-start justify-between gap-2 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-700"
        >
          <span className="whitespace-pre-line">{error}</span>
          <button type="button" onClick={() => setError(null)} className="text-red-700" aria-label="Dismiss error">
            ×
          </button>
        </div>
      )}

      {showCreateNode && data && (
        <form
          onSubmit={handleCreateNode}
          className="mb-2 flex flex-wrap items-end gap-2 rounded-md border border-slate-200 p-2"
          data-testid="create-node-form"
        >
          <label className="text-xs">
            Type
            <select name="entity_type_id" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
              <option value="">—</option>
              {data.entity_types.map((et) => (
                <option key={et.id} value={et.id}>
                  {et.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            Name
            <input name="name" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs">
            Code
            <input name="code" className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          {hierarchyId && (
            <label className="text-xs">
              Parent
              <select name="parent_entity_id" className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
                <option value="">(root)</option>
                {data.nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white">
            Create
          </button>
        </form>
      )}

      {pendingEdge && data && (
        <div className="mb-2 rounded-md border border-slate-200 p-2" data-testid="edge-type-picker">
          <p className="mb-1 text-xs text-slate-600">Choose a relationship type:</p>
          {(() => {
            const validTypes = validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId);
            if (validTypes.length === 0) {
              const sourceTypeName = entityTypeName(nodeEntityType(pendingEdge.sourceId));
              const targetTypeName = entityTypeName(nodeEntityType(pendingEdge.targetId));
              return (
                <p className="mb-1 text-xs text-slate-500">
                  No relationship type allows {sourceTypeName} → {targetTypeName}
                </p>
              );
            }
            return validTypes.map((rt) => (
              <button
                key={rt.id}
                type="button"
                onClick={() => handleConfirmEdge(rt.id)}
                className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
              >
                {rt.name}
              </button>
            ));
          })()}
          <button type="button" onClick={() => setPendingEdge(null)} className="text-sm text-slate-500">
            Cancel
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {loadError && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
