import { useEffect, useRef, useState } from "react";
import cytoscape, { Core } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
import { useGraph } from "../api/graph";
import type { GraphResponse } from "../types/graph";

cytoscape.use(elk);

type GraphEditorProps = {
  organizationId: string;
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

export default function GraphEditor({ organizationId }: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);

  const { data, isLoading, error } = useGraph(organizationId, hierarchyId);

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
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.layout(ELK_LAYOUT as any).run();
    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [data]);

  function runLayout() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current?.layout(ELK_LAYOUT as any).run();
  }

  function fit() {
    cyRef.current?.fit();
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => setHierarchyId(e.target.value || null)}
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
      </div>
      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {error && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
