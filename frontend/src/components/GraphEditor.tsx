import { FormEvent, useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { useCreateEdge, useCreateNode, useGraph } from "../api/graph";
import type { GraphResponse, RelationshipTypeOption } from "../types/graph";
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

function toElements(graph: GraphResponse) {
  const nodeElements = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      parent: node.parent ?? undefined,
    },
  }));
  const edgeElements = graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: edge.type,
    },
  }));
  return [...nodeElements, ...edgeElements];
}

const ELK_LAYOUT = { name: "elk", elk: { algorithm: "layered" } } as const;

export default function GraphEditor({
  organizationId,
  hierarchyId,
  onHierarchyChange,
  filter,
  onSelectionChange,
}: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);

  const { data, isLoading, error } = useGraph(organizationId, hierarchyId);
  const createNode = useCreateNode(organizationId, hierarchyId);
  const createEdge = useCreateEdge(organizationId, hierarchyId);

  useEffect(() => {
    if (!containerRef.current || !data) {
      return;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(data),
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
    cy.layout(ELK_LAYOUT as any).run();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const eh = (cy as any).edgehandles({});

    cy.on("tap", "node", (evt: any) => {
      onSelectionChange?.({ kind: "node", id: evt.target.id() });
    });
    cy.on("tap", "edge", (evt: any) => {
      onSelectionChange?.({ kind: "edge", id: evt.target.id() });
    });
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
    };
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

  function runLayout() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current?.layout(ELK_LAYOUT as any).run();
  }

  function fit() {
    cyRef.current?.fit();
  }

  function nodeEntityType(entityId: string): string | undefined {
    return data?.nodes.find((n) => n.id === entityId)?.type;
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
    createEdge.mutate({
      relationship_type_id: relationshipTypeId,
      source_entity_id: pendingEdge.sourceId,
      target_entity_id: pendingEdge.targetId,
    });
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
    createNode.mutate({
      organization_id: organizationId,
      entity_type_id: entityTypeId,
      name,
      code,
      hierarchy_id: hierarchyId ?? undefined,
      parent_entity_id: parentEntityId,
    });
    setShowCreateNode(false);
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
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
          onClick={() => setShowCreateNode((v) => !v)}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
      </div>

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
          {validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId).map((rt) => (
            <button
              key={rt.id}
              type="button"
              onClick={() => handleConfirmEdge(rt.id)}
              className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {rt.name}
            </button>
          ))}
          <button type="button" onClick={() => setPendingEdge(null)} className="text-sm text-slate-500">
            Cancel
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {error && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
