import { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { labelForeground } from "../../lib/colour";
import type { ModelPart } from "../../lib/modelGraph";
import { layoutModel, PART_TITLE } from "../../lib/modelLayout";
import { reteNodes, type NodeSpec } from "../../lib/modelNodes";
import type { ModelStyleProps } from "./types";

type CardData = { spec: NodeSpec; fill: string; soft: boolean };
type Card = Node<CardData, "part">;

const CARD_WIDTH = 230;

// A card's header colour: the part's own for sets and rules (a set is its
// entity type's colour, a rule dark or amber as in the graph), one per kind
// for the rest.
const HEADER: Partial<Record<ModelPart, string>> = {
  variables: "#2563eb",
  parameters: "#64748b",
  objective: "#16a34a",
};

function PartCard({ data, selected }: NodeProps<Card>) {
  const { spec, fill, soft } = data;
  const header = HEADER[spec.part] ?? fill;
  return (
    <div
      className={`overflow-hidden rounded-lg border bg-white text-left shadow-sm ${
        selected ? "border-blue-600 ring-2 ring-blue-300" : soft ? "border-dashed border-amber-500" : "border-slate-300"
      }`}
      style={{ width: CARD_WIDTH }}
    >
      {spec.inputs.length > 0 && <Handle type="target" position={Position.Left} className="!h-3 !w-3 !bg-slate-500" />}
      <div className="px-3 py-1.5" style={{ background: header, color: labelForeground(header) }}>
        <div className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{PART_TITLE[spec.part]}</div>
        <div className="truncate text-sm font-semibold" title={spec.name}>
          {spec.name}
        </div>
      </div>
      <div className="space-y-1 px-3 py-2 text-xs text-slate-700">
        {spec.subtitle && <div className="text-slate-500">{spec.subtitle}</div>}
        {spec.summary && (
          <div className="line-clamp-3 font-mono text-[11px] text-slate-800" title={spec.summary}>
            {spec.summary}
          </div>
        )}
        {spec.inputs.length > 0 && (
          <div className="text-[11px] text-slate-500">
            reads {spec.inputs.map((input) => input.label).join(", ")}
          </div>
        )}
      </div>
      {spec.output && <Handle type="source" position={Position.Right} className="!h-3 !w-3 !bg-slate-500" />}
    </div>
  );
}

const nodeTypes = { part: PartCard };

// Cards grow with what they say; the layout leaves room for that.
function cardHeight(spec: NodeSpec): number {
  const summaryLines = spec.summary ? Math.min(3, Math.ceil(spec.summary.length / 34)) : 0;
  const readsLines = spec.inputs.length ? Math.ceil(spec.inputs.map((i) => i.label).join(", ").length / 38) : 0;
  return 54 + 18 + (spec.subtitle ? 16 : 0) + summaryLines * 15 + readsLines * 15;
}

/**
 * The model as a React Flow chart: a card per part, left to right from the
 * sets to the goal, wired the way the model's dependencies run. Pan, zoom
 * and drag to rearrange; selecting a card opens its side panel.
 */
export default function FlowView({ graph, palette, onSelect, positions, onMove }: ModelStyleProps & {
  positions?: Record<string, { x: number; y: number }>;
  onMove?: (id: string, position: { x: number; y: number }) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const specs = reteNodes(graph);
    const byId = new Map(specs.map((spec) => [spec.id, spec]));
    const boxes = layoutModel(graph, (id) => ({ width: CARD_WIDTH, height: cardHeight(byId.get(id)!) }), {
      columnGap: 120,
      rowGap: 26,
    });
    const nodes: Card[] = specs.map((spec) => ({
      id: spec.id,
      type: "part",
      position: positions?.[spec.id] ?? { x: boxes.get(spec.id)?.x ?? 0, y: boxes.get(spec.id)?.y ?? 0 },
      data: { spec, fill: palette.nodeFill[spec.id] ?? "#e2e8f0", soft: palette.nodeData?.[spec.id]?.soft === "yes" },
      connectable: false,
    }));
    const edges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "default",
      label: edge.label || undefined,
      animated: edge.label === "penalty",
      style: {
        stroke: palette.edgeColour[edge.id] ?? "#475569",
        strokeWidth: 1.5,
        strokeDasharray: edge.type === "ranges" ? "4 3" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: palette.edgeColour[edge.id] ?? "#475569" },
      labelStyle: { fontSize: 10, fill: "#334155" },
      labelBgStyle: { fill: "#f8fafc" },
    }));
    return { nodes, edges };
  }, [graph, palette, positions]);

  return (
    <div className="h-full w-full" data-testid="model-style-view-flow">
      {/* Uncontrolled, so cards can be dragged aside; a different model
          remounts it through the key rather than fighting its state. */}
      <ReactFlow
        key={nodes.map((node) => node.id).join("|")}
        defaultNodes={nodes}
        defaultEdges={edges}
        nodeTypes={nodeTypes}
        nodesConnectable={false}
        onNodeClick={(_event, node) => onSelect(node.id)}
        onNodeDragStop={(_event, node) => onMove?.(node.id, node.position)}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.2}
        proOptions={{ hideAttribution: false }}
      >
        <Background gap={18} color="#cbd5e1" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(node) => HEADER[(node.data as CardData).spec.part] ?? (node.data as CardData).fill} />
      </ReactFlow>
    </div>
  );
}
