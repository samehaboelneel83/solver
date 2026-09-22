import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { relationshipErrorMessage, useGraphView } from "../api/graph";
import {
  useCreateEntity,
  useCreateRelationship,
  useEntityTypes,
  useRelationshipTypes,
  type Id,
} from "../api/v1";
import {
  collapseGraph,
  descendantIds,
  hiddenByCollapse,
  parentIds,
} from "../lib/hierarchyCollapse";
import {
  isErDecoration,
  objectsPalette,
  withErDependents,
  type GraphMode,
  type GraphPalette,
} from "../lib/typesGraph";
import { runErLayout } from "../lib/erLayout";
import ModelPicker from "./ModelPicker";
import type { ModelTarget, ModelTargetRequest } from "../hooks/useModelTarget";
import AttrsForm, { buildAttrs, type AttrDrafts } from "./AttrsForm";
import { FieldError, FieldLabel, INPUT_CLASS, type FieldErrors } from "./attrTypes";
import { entityServerErrors } from "../pages/EntityRecord";
import OfflineNotice from "./OfflineNotice";
import { useCapabilities } from "../hooks/useCapability";
import { useToast } from "./ToastProvider";
import type { GraphEdge, GraphNode, GraphResponse, RelationshipTypeOption } from "../types/graph";
import type { FilterCriteria } from "./FilterBar";

cytoscape.use(elk);
cytoscape.use(edgehandles);

type Selection = { kind: "node" | "edge"; id: string } | null;

type GraphEditorProps = {
  domainId: Id;
  /** Which view to draw -- the domain's objects, or its schema. Owned by
   * the page (it also lives in the URL and in localStorage); this
   * component only renders the toggle and redraws. */
  mode: GraphMode;
  onModeChange: (mode: GraphMode) => void;
  /** A `relationship_type` with `is_hierarchy = true`, whose rows become the
   * nodes' compound parents. Null draws the graph flat. */
  hierarchyTypeId: Id | null;
  onHierarchyTypeChange: (id: Id | null) => void;
  /** The optimization view's problem and model version, resolved by the page
   * (`useModelTarget`), and how to ask for another. Unused by the others. */
  modelTarget?: ModelTarget;
  onModelTargetChange?: (request: ModelTargetRequest) => void;
  filter?: FilterCriteria;
  onSelectionChange?: (selection: Selection) => void;
  // H-1 fix round 1: an external request to move the canvas's own roving keyboard focus to a
  // node -- e.g. GraphDemo's search-select (Enter in FilterBar's search box). `token` is a
  // strictly-increasing counter so the same `nodeId` requested twice (or a request that follows
  // a plain mouse tap, which does NOT go through this prop) still re-centres/re-announces it.
  focusRequest?: { nodeId: string; token: number } | null;
};

const ELK_LAYOUT = {
  name: "elk",
  elk: { algorithm: "layered", "elk.hierarchyHandling": "INCLUDE_CHILDREN" },
} as const;

// Only reached when an element has no palette entry at all -- i.e. the two
// halves of a payload disagree. The old fixed canvas colours, so such an
// element looks like the graph did before this task rather than invisible.
const FALLBACK_FILL = "#0f172a";
const FALLBACK_LABEL = "#f8fafc";
const FALLBACK_EDGE = "#94a3b8";
// Edge labels sit on the canvas background, not on a fill, so they do NOT
// take a computed foreground: they are dark text with a white halo, which
// reads over the background and over any edge passing beneath them. Only
// node labels sit on a user-chosen colour, and only those are computed.
const EDGE_LABEL = "#0f172a";
const EDGE_LABEL_HALO = "#ffffff";

/**
 * The canvas stylesheet. Exported so the data-driven fills can be asserted
 * -- everything cytoscape actually paints is inside a `<canvas>`, where
 * neither a test nor axe can see it, so the mapping from element data to
 * colour is the last observable point.
 */
export function graphStylesheet() {
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        // The entity type's colour (or its deterministic fallback), and a
        // label colour computed from that fill's luminance -- see
        // `lib/colour.ts`. F-3 was fixed by giving the label an outline in
        // the node's own colour: a label drifting over a neighbour still
        // reads, because its halo is its own node's fill.
        "background-color": "data(colour)",
        color: "data(labelColour)",
        "text-outline-width": 2,
        "text-outline-color": "data(colour)",
        "font-size": "10px",
        width: 30,
        height: 30,
      },
    },
    {
      // A compound (parent) node is drawn as a pale tint of its type's
      // colour, so the label does NOT sit on that colour and the computed
      // foreground would be the wrong answer -- a light label on a 15%
      // tint of a dark fill is unreadable. Fixed dark-on-white instead,
      // which is correct for every tint.
      selector: "$node > node",
      style: {
        "background-color": "data(colour)",
        "background-opacity": 0.15,
        "border-width": 1,
        "border-color": "data(colour)",
        color: EDGE_LABEL,
        "text-outline-color": EDGE_LABEL_HALO,
      },
    },
    {
      selector: "edge",
      style: {
        label: "data(label)",
        "font-size": "9px",
        // The types view puts the cardinality on a second line.
        "text-wrap": "wrap",
        color: EDGE_LABEL,
        "text-outline-width": 2,
        "text-outline-color": EDGE_LABEL_HALO,
        width: 2,
        "line-color": "data(colour)",
        "target-arrow-color": "data(colour)",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
      },
    },
    // -- the types view, as an ER diagram (lib/typesGraph.ts, lib/erLayout.ts) --
    // Chen's notation: rectangles, diamonds, ellipses. Sizes come from the
    // label, estimated where the drawing is built, so text stays inside its
    // shape.
    {
      selector: 'node[er = "entity"]',
      style: {
        shape: "rectangle",
        width: "data(w)",
        height: 46,
        "font-size": "16px",
        "font-weight": "bold",
        "text-valign": "center",
        "text-halign": "center",
        "border-width": 1.5,
        "border-color": "#1e293b",
      },
    },
    {
      selector: 'node[er = "relationship"]',
      style: {
        shape: "diamond",
        width: "data(w)",
        height: 62,
        "font-size": "13px",
        "text-valign": "center",
        "text-halign": "center",
        "border-width": 1.5,
        "border-color": "#1e293b",
      },
    },
    {
      // A hierarchy is a relationship a type has with itself that also nests
      // it; the double border tells it apart from an ordinary recursive one.
      selector: 'node[er = "relationship"][hierarchy = "yes"]',
      style: { "border-width": 4, "border-style": "double" },
    },
    {
      // White with dark text whatever the owner's colour: an attribute
      // describes its owner, and forty coloured ellipses would drown the
      // rectangles they describe. No halo -- the text sits on white.
      selector: 'node[er = "attribute"]',
      style: {
        shape: "ellipse",
        width: "data(w)",
        height: 28,
        "font-size": "13px",
        "text-valign": "center",
        "text-halign": "center",
        "text-outline-width": 0,
        "border-width": 1.2,
        "border-color": "#475569",
      },
    },
    {
      selector: 'edge[er = "attribute-link"]',
      style: {
        width: 1.2,
        "curve-style": "straight",
        "target-arrow-shape": "none",
        label: "",
      },
    },
    {
      // Plain lines in the notation -- the direction is in the cardinality
      // at each end, not in an arrowhead. Bezier rather than straight so
      // the two lines of a hierarchy, which join the same pair of nodes,
      // bow apart instead of lying on top of each other.
      selector: 'edge[er = "connector"]',
      style: {
        width: 2,
        "curve-style": "bezier",
        "target-arrow-shape": "none",
        label: "",
        "source-label": "data(end)",
        "source-text-offset": 26,
        "font-size": "13px",
        "font-weight": "bold",
      },
    },
    {
      // The `to` line runs diamond -> type, so its cardinality belongs at
      // the target end, beside the rectangle.
      selector: 'edge[er = "connector"][endAt = "target"]',
      style: {
        "source-label": "",
        "target-label": "data(end)",
        "target-text-offset": 26,
      },
    },
    // -- the optimization view (lib/modelGraph.ts) --
    // Two-line labels: a name, then what the part is (domain and index, or
    // whether the rule may bend). Sizes come from the label, estimated where
    // the drawing is built.
    {
      selector: 'node[er = "set"], node[er = "variable"], node[er = "parameter"], node[er = "constraint"], node[er = "objective"]',
      style: {
        width: "data(w)",
        height: 50,
        "font-size": "13px",
        "text-wrap": "wrap",
        "text-valign": "center",
        "text-halign": "center",
        "border-width": 1.5,
        "border-color": "#1e293b",
      },
    },
    { selector: 'node[er = "set"]', style: { shape: "rectangle", height: 44, "font-size": "15px", "font-weight": "bold" } },
    { selector: 'node[er = "variable"]', style: { shape: "ellipse", "border-color": "#1d4ed8", "text-outline-width": 0 } },
    { selector: 'node[er = "parameter"]', style: { shape: "round-rectangle", "border-color": "#64748b", "text-outline-width": 0 } },
    { selector: 'node[er = "constraint"]', style: { shape: "hexagon", height: 56 } },
    {
      // A rule that may bend: amber, dashed -- it holds unless holding costs
      // more than the price of breaking it.
      selector: 'node[er = "constraint"][soft = "yes"]',
      style: { "border-style": "dashed", "border-width": 2, "border-color": "#b45309", "text-outline-width": 0 },
    },
    { selector: 'node[er = "objective"]', style: { shape: "octagon", height: 60, "font-weight": "bold" } },
    {
      selector: 'edge[er = "uses"], edge[er = "ranges"]',
      style: {
        width: 1.6,
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.9,
        "font-size": "11px",
      },
    },
    {
      // "Ranges over" -- a set indexing something, or a rule holding for
      // every member -- is structure rather than arithmetic, so it is drawn
      // lighter than a variable or parameter feeding a rule.
      selector: 'edge[er = "ranges"]',
      style: { "line-style": "dashed", width: 1.2 },
    },
    { selector: ".graph-highlighted", style: { "border-width": 3, "border-color": "#2563eb" } },
    { selector: ".graph-dimmed", style: { opacity: 0.25 } },
    // H-1: the visible ring for the node currently holding keyboard (roving) focus.
    { selector: ".kb-focus", style: { "border-width": 4, "border-color": "#f59e0b", "border-style": "solid" } },
  ];
}

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
export function applyGraphToCy(
  cy: Core,
  graph: GraphResponse,
  // Defaulted rather than required so a caller that only has a payload
  // (and the tests that predate colours) still gets the objects-mode
  // resolution instead of an uncoloured canvas.
  palette: GraphPalette = objectsPalette(graph)
): { structureChanged: boolean } {
  let structureChanged = false;
  // Cytoscape maps `data(colour)` / `data(labelColour)` onto the fill and
  // the label (see `graphStylesheet`), so the colours travel in element
  // data rather than as per-element `.style()` calls: a style set on an
  // element wins over the stylesheet forever and would have to be cleared
  // by hand when a type's colour changes.
  // `nodeData` / `edgeData` carry what the ER drawing adds (shape kind,
  // estimated width, cardinality end labels, what a tap selects) -- merged in
  // here so the stylesheet can select on it. The objects view has none.
  const nodeStyle = (id: string) => ({
    ...(palette.nodeData?.[id] ?? {}),
    colour: palette.nodeFill[id] ?? FALLBACK_FILL,
    labelColour: palette.nodeLabel[id] ?? FALLBACK_LABEL,
  });
  const edgeStyle = (id: string) => ({
    ...(palette.edgeData?.[id] ?? {}),
    colour: palette.edgeColour[id] ?? FALLBACK_EDGE,
  });

  const desiredNodes = new Map(graph.nodes.map((n) => [n.id, n]));
  // Keyed by CANVAS id -- see `cyEdgeId`. `edge.id` (the wire id) is still
  // what styles are resolved by and what travels as `graphId`.
  const desiredEdges = new Map(graph.edges.map((e) => [cyEdgeId(e.id), e]));

  const existingNodeIds = new Set<string>();
  const existingEdgeIds = new Set<string>();
   
  (cy as any)
    .nodes()
    .forEach((ele: any) => existingNodeIds.add(ele.id()));
   
  (cy as any)
    .edges()
    .forEach((ele: any) => existingEdgeIds.add(ele.id()));

  existingNodeIds.forEach((id) => {
    if (!desiredNodes.has(id)) {
       
      (cy as any).remove?.((cy as any).getElementById(id));
      structureChanged = true;
    }
  });
  existingEdgeIds.forEach((id) => {
    if (!desiredEdges.has(id)) {
       
      (cy as any).remove?.((cy as any).getElementById(id));
    }
  });

  const newNodes: GraphNode[] = [];
  desiredNodes.forEach((node, id) => {
    if (existingNodeIds.has(id)) {
       
      const ele = (cy as any).getElementById(id);
      ele.data({ label: node.label, type: node.type, ...nodeStyle(id) });
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

  // An edge whose source/target isn't among the nodes that will actually exist in cy (kept
  // existing ones + the ones we're about to add) can't be created -- real Cytoscape's cy.add()
  // throws synchronously ("Can not create edge ... with nonexistent source/target"), which would
  // abort the whole batch. Skip those rather than let a dangling edge take down the update.
  const validNodeIds = new Set(graph.nodes.map((n) => n.id));
  let skippedEdgeCount = 0;

  const newEdges: GraphEdge[] = [];
  desiredEdges.forEach((edge, id) => {
    if (existingEdgeIds.has(id)) {
       
      const ele = (cy as any).getElementById(id);
      ele.data({ label: edge.label, type: edge.type, ...edgeStyle(id) });
    } else if (!validNodeIds.has(edge.source) || !validNodeIds.has(edge.target)) {
      skippedEdgeCount += 1;
    } else {
      newEdges.push(edge);
    }
  });

  if (skippedEdgeCount > 0 && typeof console !== "undefined") {
     
    console.warn(`applyGraphToCy: skipped ${skippedEdgeCount} edge(s) referencing a missing node`);
  }

  if (newNodes.length > 0 || newEdges.length > 0) {
     
    const extent = (cy as any).extent?.() ?? { x1: 0, y1: 0, x2: 0, y2: 0 };
    const center = { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 };
    const elementsToAdd = [
      // Each new node gets its OWN position object -- cytoscape stores `position` by reference
      // (no clone) and later mutates it in place when the layout repositions a node, so nodes
      // that shared one `center` object would all keep reflecting whichever node's position was
      // set last, collapsing the whole graph onto a single point after layout.
      ...newNodes.map((node) => ({
        data: {
          id: node.id,
          label: node.label,
          type: node.type,
          parent: node.parent ?? undefined,
          ...nodeStyle(node.id),
        },
        position: { x: center.x, y: center.y },
      })),
      ...newEdges.map((edge) => ({
        data: {
          id: cyEdgeId(edge.id),
          graphId: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          type: edge.type,
          ...edgeStyle(edge.id),
        },
      })),
    ];
     
    (cy as any).add?.(elementsToAdd);
    if (newNodes.length > 0) {
      structureChanged = true;
    }
  }

  return { structureChanged };
}

const GRID_LAYOUT = { name: "grid" } as const;

const MODEL_LAYOUT = {
  name: "elk",
  fit: false,
  // Columns by what a part IS, not only by where its edges happen to lead:
  // a set that only feeds rules directly (unit, in the workforce model)
  // would otherwise be layered beside the variables, and the objective could
  // land mid-page. Sets first, objective last; the rest falls in between.
  nodeLayoutOptions: (node: { data: (key: string) => unknown }) => {
    const kind = node.data("er");
    if (kind === "set") return { "elk.layered.layering.layerConstraint": "FIRST" };
    if (kind === "objective") return { "elk.layered.layering.layerConstraint": "LAST" };
    return {};
  },
  elk: {
    algorithm: "layered",
    "elk.direction": "RIGHT",
    "elk.spacing.nodeNode": 24,
    "elk.layered.spacing.nodeNodeBetweenLayers": 70,
    "elk.spacing.componentComponent": 40,
  },
} as const;

/** The toggle's words, and the canvas's name for each view. The mode values
 * (`types`, `objects`, `model`) predate them and stay, because they are in
 * stored preferences and in links. */
export const VIEW_NAME: Record<GraphMode, string> = {
  types: "ERD View",
  objects: "Graph View",
  model: "Optimization View",
};

const VIEW_TITLE: Record<GraphMode, string> = {
  types: "Show this domain's schema as an entity-relationship diagram",
  objects: "Show this domain's entities and the relationships between them",
  model: "Show a problem's optimization model: its sets, variables, parameters, rules and objective",
};

/** In the order the toggle offers them: the schema, the data, the model. */
const VIEW_ORDER: readonly GraphMode[] = ["types", "objects", "model"];

/**
 * What tapping (or pressing Enter on) an element selects.
 *
 * Usually the element itself -- a node by its id, an edge by its wire id
 * (see `cyEdgeId`). The ER drawing overrides that through `selectKind` /
 * `selectId`: a diamond and its two lines select the relationship type, as
 * the single edge they replaced did, and an attribute selects its owner. So
 * the side panel resolves exactly the selections it always has.
 */
export function selectionOf(
  element: { id: () => string; data?: (key: string) => unknown },
  // Which handler fired: the fallback when the element says nothing about
  // itself, which is every element outside the ER drawing.
  as: "node" | "edge"
): { kind: "node" | "edge"; id: string } {
  const read = (key: string) => (typeof element.data === "function" ? element.data(key) : undefined);
  const kind = read("selectKind");
  const id = read("selectId");
  if ((kind === "node" || kind === "edge") && typeof id === "string") {
    return { kind, id };
  }
  if (as === "node") return { kind: "node", id: element.id() };
  // The wire id, not the canvas id -- see `cyEdgeId`.
  return { kind: "edge", id: String(read("graphId") ?? element.id()) };
}

/**
 * The canvas id for a wire edge.
 *
 * Cytoscape keeps nodes and edges in **one** id space, and answers an
 * `add()` whose id is already taken by silently doing nothing -- no throw,
 * no console message, the element simply never appears. The objects view's
 * node ids are `entity.id` and its edge ids are `relationship.id`: two
 * independent bigint identity sequences, so in any database seeded from
 * empty they overlap from the first row, and the overlapping edges vanish.
 * Measured on the seeded demo: 23 nodes drawn, 10 relationships on the
 * wire, **0** edges on the canvas.
 *
 * The types view already avoids this by minting `type-`/`reltype-` ids
 * (`lib/typesGraph.ts`); this is the same idea for the objects view, but
 * applied at the canvas boundary rather than on the wire, so the payload
 * contract in `types/graph.ts` is untouched. The wire id travels on the
 * element as `graphId`, because that is what the property panel and
 * `DELETE /api/v1/relationships/{id}` need.
 */
export function cyEdgeId(wireId: string): string {
  return `edge:${wireId}`;
}

/**
 * True when `positions` has 2+ points that are all within 1px of each other in both x and y --
 * i.e. a layout that computed distinct per-node results but somehow left every node stacked on
 * the same spot (see the `center`-object-sharing bug applyGraphToCy guards against above; kept
 * as a runtime safety net for any other cause, e.g. a genuine ELK failure).
 */
/** How many nodes a person would count: every node, except the ER
 * drawing's attribute ellipses, which describe a node rather than being one.
 * Six entity types with forty attributes is "6 nodes", not 46. */
export function countable(nodes: readonly GraphNode[]): number {
  return nodes.filter((node) => !isErDecoration(node)).length;
}

export function positionsAreDegenerate(positions: { x: number; y: number }[]): boolean {
  if (positions.length < 2) {
    return false;
  }
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of positions) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  return maxX - minX < 1 && maxY - minY < 1;
}

export default function GraphEditor({
  domainId,
  mode,
  onModeChange,
  hierarchyTypeId,
  onHierarchyTypeChange,
  filter,
  onSelectionChange,
  focusRequest,
  modelTarget,
  onModelTargetChange,
}: GraphEditorProps) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const isTypes = mode === "types";
  const isModel = mode === "model";
  // The entity graph -- the only view that writes rows (Connect, create,
  // nesting by hierarchy). Both others are read-only drawings of a schema.
  const isObjects = mode === "objects";
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
   
  const ehRef = useRef<any>(null);
  const graphRef = useRef<GraphResponse | null>(null);
  const hasLaidOutRef = useRef(false);
  // The mount effect (below) registers cy event handlers exactly once, so they close over
  // whatever `onSelectionChange` was at that first render. Route through a ref, kept current on
  // every render, so a later render's new callback is the one actually invoked on tap.
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  // What the last Connect gesture did when it produced no picker. Null
  // most of the time; see the `ehcancel` handler for why it exists.
  const [connectNote, setConnectNote] = useState<string | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);
  // The create-node form is a small `entity` form: a key, an optional label
  // and one control per `attribute_def` of the chosen type (Task 12's
  // AttrsForm), plus a parent when a hierarchy is selected.
  const [createTypeId, setCreateTypeId] = useState<Id | "">("");
  const [createKey, setCreateKey] = useState("");
  const [createLabel, setCreateLabel] = useState("");
  const [createParentId, setCreateParentId] = useState("");
  const [createDrafts, setCreateDrafts] = useState<AttrDrafts>({});
  const [createErrors, setCreateErrors] = useState<FieldErrors>({});
  // Compound parents nest; they do not hide. This is the other half of a
  // hierarchy: which parents currently sit on their descendants.
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
  const createFormId = useId();
  const [connecting, setConnecting] = useState(false);
  const [layoutStatus, setLayoutStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // H-1: the roving keyboard selection on the canvas -- which node last received Arrow-key
  // focus, and the text a polite live region announces as it moves. Derived fresh from the
  // live cytoscape instance at each keypress (see orderedNodeIds) rather than cached, so it
  // stays correct as nodes are added/removed/relaid-out.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [focusedEdgeCyId, setFocusedEdgeCyId] = useState<string | null>(null);
  // Keyboard connect: the node C was pressed on, waiting for Enter on another.
  const [connectFromId, setConnectFromId] = useState<string | null>(null);
  const [liveMessage, setLiveMessage] = useState("");
  // H-7: the create-node toggle is the trigger for the form below -- Escape inside the form
  // closes it and returns focus here, rather than dropping focus back to the document body.
  const createNodeToggleRef = useRef<HTMLButtonElement | null>(null);
  // H-1: Escape on the canvas returns focus to the toolbar's first control (the hierarchy
  // select) rather than dropping it back to the document body.
  // In the types view the hierarchy select is not rendered (there are no
  // relationship ROWS to nest anything by), so the view toggle is the first
  // control and takes the ref instead.
  const firstControlRef = useRef<HTMLElement | null>(null);

  function resetCreateNodeForm() {
    setCreateTypeId("");
    setCreateKey("");
    setCreateLabel("");
    setCreateParentId("");
    setCreateDrafts({});
    setCreateErrors({});
  }

  function closeCreateNodeForm() {
    setShowCreateNode(false);
    resetCreateNodeForm();
    createNodeToggleRef.current?.focus();
  }

  function openCreateNodeForm() {
    setShowCreateNode(true);
    resetCreateNodeForm();
  }

  function handleCreateNodeFormKeyDown(event: ReactKeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      closeCreateNodeForm();
    }
  }

  const {
    data,
    palette,
    isLoading,
    error: loadError,
    refetch: refetchGraph,
    fetchStatus: graphFetchStatus,
  } = useGraphView(domainId, hierarchyTypeId, mode, modelTarget?.versionId ?? null);
  // Collapse only when a hierarchy is actually nesting the canvas. A
  // flat objects view, and the types view, have no compound parents to
  // sit on -- Minus must not remove nodes there.
  const nesting = isObjects && hierarchyTypeId !== null;

  useEffect(() => {
    setCollapsedIds(new Set());
  }, [hierarchyTypeId, mode]);

  // D-7: offline, this query pauses instead of failing -- `isLoading` never resolves, so
  // without this the "Loading graph…" text below would sit there forever.
  const isOffline = graphFetchStatus === "paused" && !data;
  // The hierarchy picker is filtered SERVER-side: `is_hierarchy` is a column
  // on `relationship_type`, and Task 7 added the filter for exactly this.
  const hierarchyTypes = useRelationshipTypes(domainId, { isHierarchy: true, limit: 500 });
  // The graph payload's `attribute_definitions` carry only id/name/data_type;
  // AttrsForm needs `required`, `enum_values`, `unit` and `default_value` as
  // well, which the entity-type list route carries in full. Same query the
  // property panel runs, so React Query serves it once.
  const entityTypes = useEntityTypes(domainId, { limit: 500 });
  const createEntity = useCreateEntity();
  const createRelationship = useCreateRelationship();
  const toast = useToast();

  const createType = createTypeId === "" ? undefined : entityTypes.data?.items.find((t) => t.id === createTypeId);
  const createAttributes = createType?.attributes ?? [];

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
       
      style: graphStylesheet() as any,
    });

     
    const eh = (cy as any).edgehandles({});
    ehRef.current = eh;

     
    cy.on("tap", "node", (evt: any) => {
      onSelectionChangeRef.current?.(selectionOf(evt.target, "node"));
    });

    cy.on("tap", "edge", (evt: any) => {
      onSelectionChangeRef.current?.(selectionOf(evt.target, "edge"));
    });
     
    cy.on("tap", (evt: any) => {
      if (evt.target === cy) {
        onSelectionChangeRef.current?.(null);
      }
    });
    cy.on("ehcomplete", (_event: unknown, sourceNode: NodeSingular, targetNode: NodeSingular) => {
      setConnectNote(null);
      setPendingEdge({ sourceId: sourceNode.id(), targetId: targetNode.id() });
    });
    /**
     * The gesture ended without a target.
     *
     * edgehandles emits this whenever the pointer is released away from a
     * node -- and nothing listened, so a Connect drag that missed was
     * completely silent: no picker, no banner, no change. That is
     * indistinguishable from a drag the product refused, so the next move
     * is to try again, harder. It is also the likeliest outcome on the
     * cramped default layout, where a node can sit half outside the
     * viewport.
     */
    cy.on("ehcancel", () => {
      setPendingEdge(null);
      setConnectNote(
        "Nothing was connected: the drag did not end on another node. " +
          "Press on one node and release on the node you want to connect it to."
      );
    });
    // A new gesture describes itself; whatever the last one said is no
    // longer about anything on screen.
    cy.on("ehstart", () => {
      setConnectNote(null);
      setPendingEdge(null);
    });

    cyRef.current = cy;

    return () => {
      eh.destroy();
      cy.destroy();
      cyRef.current = null;
      ehRef.current = null;
      hasLaidOutRef.current = false;
    };
     
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    if (loadError) {
      // The org/hierarchy query just failed -- whatever was drawn from a
      // previous successful query is now stale and unconfirmed (e.g. it
      // could belong to a different organisation entirely). Clear it so
      // there's nothing left on the canvas that looks actionable; "data
      // becomes undefined because the query key changed" (a normal
      // in-flight refetch, no error) intentionally does NOT hit this branch
      // and leaves the current drawing alone until the new data arrives.
      cy.elements().remove();
      hasLaidOutRef.current = false;
      return;
    }
    if (!data) {
      return;
    }
    const drawn = nesting ? collapseGraph(data, collapsedIds) : data;
    const { structureChanged } = applyGraphToCy(cy, drawn, palette);
    graphRef.current = data;
    if (structureChanged || !hasLaidOutRef.current) {
      hasLaidOutRef.current = true;
      startLayout(cy);
    }
    // `palette` is a fresh object per render of its inputs, so it is read
    // here rather than listed as a dependency -- the data it is derived
    // from is already in the list, and adding it would re-diff on every
    // render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, loadError, nesting, collapsedIds]);

  // A mode switch replaces every element (types ids are namespaced, so the
  // diff is a clean remove/add) and must announce itself: the toggle is a
  // pair of buttons whose pressed state changes, which a screen reader
  // reads as a button state, not as "the canvas now shows something else".
  // Skipped on the first render so arriving on the page does not announce
  // a change that did not happen.
  const announcedModeRef = useRef<GraphMode>(mode);
  useEffect(() => {
    if (announcedModeRef.current === mode) {
      return;
    }
    announcedModeRef.current = mode;
    setFocusedNodeId(null);
    // Both belong to the objects view; leaving them open across a switch
    // would offer to create an entity on a canvas that has none.
    setShowCreateNode(false);
    setPendingEdge(null);
    setLiveMessage(
      mode === "types"
        ? "Types view: entity types and relationship types"
        : "Objects view: entities and relationships"
    );
  }, [mode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) {
      return;
    }
    const searchLower = (filter?.search ?? "").toLowerCase();
    // Built once per run instead of re-deriving per node: a Map for O(1) id
    // lookup instead of `Array.find`, and a Set for O(1) membership instead
    // of `Array.includes` -- both were previously re-scanned for every node
    // on every filter/data change, O(n*m) over the whole graph.
    const nodeById = new Map(data.nodes.map((n) => [n.id, n]));
    const selectedTypesSet = filter?.selectedTypes ? new Set(filter.selectedTypes) : null;
    const highlightIds = filter?.highlightIds ?? null;
    // Task 14c. Null means "no expression constraint" -- an empty or
    // invalid expression filters nothing rather than blanking the canvas.
    const expressionMatchIds = filter?.expressionMatchIds ?? null;

    // In the ER drawing an attribute shows exactly when its owner does and a
    // diamond when both of its types do -- `withErDependents`. Every other
    // node is judged by the three filters below.
    const showing = withErDependents(data.nodes, (graphNode) => {
      const typeOk = selectedTypesSet === null || selectedTypesSet.has(graphNode.type);
      // Label only. v0 also matched `attributes.code`, which was the entity's
      // own `code` COLUMN; v1 has no such column -- `code` there would be an
      // ordinary attribute that a type may or may not declare, so matching it
      // would make search mean something different per entity type.
      const searchOk = !searchLower || graphNode.label.toLowerCase().includes(searchLower);
      // AND, and the same `display: none` the other two use -- so a node an
      // expression hid is indistinguishable downstream (edges, hit-testing,
      // the empty-state overlay) from one a checkbox hid.
      const expressionOk = expressionMatchIds === null || expressionMatchIds.has(graphNode.id);
      return typeOk && searchOk && expressionOk;
    });
    cy.nodes().forEach((node) => {
      if (!nodeById.has(node.id())) {
        return;
      }
      node.style("display", showing.has(node.id()) ? "element" : "none");
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

  // The ids the three filters leave showing -- the same AND the effect
  // above writes into `display`, derived from the graph DATA so that what
  // the page says is what was decided rather than what a style write
  // happened to leave behind. Two things read it: the canvas's accessible
  // name, and the expression announcement.
  const shownNodeIds = useMemo(() => {
    if (!data) {
      return null;
    }
    const selectedTypesSet = filter?.selectedTypes ? new Set(filter.selectedTypes) : null;
    const searchLower = (filter?.search ?? "").toLowerCase();
    const matchIds = filter?.expressionMatchIds ?? null;
    const collapsedAway = nesting ? hiddenByCollapse(data.nodes, collapsedIds) : null;
    return withErDependents(
      data.nodes,
      (node) =>
        (selectedTypesSet === null || selectedTypesSet.has(node.type)) &&
        (!searchLower || node.label.toLowerCase().includes(searchLower)) &&
        (matchIds === null || matchIds.has(node.id)) &&
        (collapsedAway === null || !collapsedAway.has(node.id))
    );
  }, [data, filter, nesting, collapsedIds]);

  // A filter that hides the node the roving selection is on drops the
  // selection rather than leaving a ring on something nobody can see. The
  // next arrow key then starts from the first visible node.
  useEffect(() => {
    if (!focusedNodeId || !shownNodeIds || shownNodeIds.has(focusedNodeId)) {
      return;
    }
     
    (cyRef.current as any)?.getElementById?.(focusedNodeId)?.removeClass?.("kb-focus");
    setFocusedNodeId(null);
  }, [shownNodeIds, focusedNodeId]);

  /**
   * The canvas's accessible name.
   *
   * It says how many nodes are SHOWN, and -- only when a filter is hiding
   * some -- how many exist. Unconditionally saying "N of M" would make an
   * unfiltered canvas sound filtered; saying only "M" is what it used to
   * do, and that was a plain untruth on a filtered one.
   */
  const canvasLabel = useMemo(() => {
    const total = countable(data?.nodes ?? []);
    const shown = shownNodeIds ? countable((data?.nodes ?? []).filter((n) => shownNodeIds.has(n.id))) : total;
    const count = shown === total ? `${total} nodes` : `${shown} of ${total} nodes shown`;
    return `Graph canvas, ${VIEW_NAME[mode].toLowerCase()}, ${count} — use the arrow keys to move between nodes`;
  }, [data, shownNodeIds, mode]);

  /**
   * What the two text filters left showing, announced in the live region
   * the rest of this canvas uses.
   *
   * Task 14c gave the expression this treatment. The search box beside it
   * did not have it, and it is the more destructive of the two: typing a
   * name cut the canvas from 23 nodes to 1, live, before Enter, with
   * nothing on screen saying so -- so the one action that answers "where
   * is this person" silently threw away the picture of who they work
   * with, next to a control that reports exactly the same thing about
   * itself. Both now report, in the same words.
   *
   * ONE effect, not two beside each other: with the search and the
   * conditions both on, two effects would each write this region on every
   * render and the last one to run would decide what a screen reader
   * heard. It also means clearing one while the other is still hiding
   * nodes announces what is still hiding them, rather than "cleared".
   *
   * The type checkboxes still do not announce -- they are checkboxes,
   * whose own state a screen reader already reads -- and the search is
   * announced from the DEBOUNCED value GraphDemo holds, so this is one
   * announcement per pause, not one per keystroke.
   */
  const announcedFilterRef = useRef<"search" | "conditions" | "both" | null>(null);
  useEffect(() => {
    if (!data || !shownNodeIds) {
      return;
    }
    const search = (filter?.search ?? "").trim();
    const conditions = Boolean(filter?.expressionMatchIds);
    const active = search && conditions ? "both" : search ? "search" : conditions ? "conditions" : null;
    if (!active) {
      const was = announcedFilterRef.current;
      if (was) {
        announcedFilterRef.current = null;
        setLiveMessage(
          was === "search"
            ? "Search cleared"
            : was === "conditions"
              ? "Filter conditions cleared"
              : "Search and filter conditions cleared"
        );
      }
      return;
    }
    announcedFilterRef.current = active;
    const what =
      active === "search"
        ? `Search "${search}"`
        : active === "conditions"
          ? "Filter conditions"
          : `Search "${search}" and filter conditions`;
    setLiveMessage(
      `${what}: ${countable(data.nodes.filter((n) => shownNodeIds.has(n.id)))} of ${countable(data.nodes)} nodes shown`
    );
  }, [filter, data, shownNodeIds]);

  /*
   * A Connect gesture that produced no relationship has to reach a screen
   * reader too, and neither of the two ways that happens moves focus or
   * changes a control's state -- so without this the canvas stayed as
   * silent for a screen-reader user as it looked for a sighted one.
   */
  useEffect(() => {
    if (connectNote) setLiveMessage(connectNote);
  }, [connectNote]);

  useEffect(() => {
    if (!pendingEdge || !data || !isObjects) {
      return;
    }
    if (validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId).length > 0) {
      return;
    }
    setLiveMessage(
      `No relationship type joins ${nodeEntityType(pendingEdge.sourceId) ?? "?"} to ` +
        `${nodeEntityType(pendingEdge.targetId) ?? "?"}, so "${nodeLabelOf(pendingEdge.sourceId)}" ` +
        `cannot be connected to "${nodeLabelOf(pendingEdge.targetId)}".`
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingEdge, data, isObjects]);

  // H-1 fix round 1: an external request (currently: GraphDemo's search-select, Enter in
  // FilterBar's search box) to move the canvas's own roving keyboard focus to a node, so the
  // property panel it just opened and the canvas's `.kb-focus` ring/live-region stay in step.
  // Keyed on `focusRequest.token` (not `.nodeId`) so a repeat request for the same node still
  // re-centres/re-announces it; a plain mouse tap does NOT flow through this effect, since
  // GraphDemo only bumps the token from its search handler, not from every selection change.
  useEffect(() => {
    const cy = cyRef.current;
    if (!focusRequest || !cy) {
      return;
    }
    // Only act on a node this graph actually holds. The effect also runs on a
    // fresh mount, so a request left over from a previous instance (switching
    // organization remounts this component) would otherwise ring and announce
    // an id that no longer exists here.
    if ((cy as any).getElementById?.(focusRequest.nodeId)?.length === 0) {
      return;
    }
    focusNode(focusRequest.nodeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest?.token]);

  function startLayout(cy: Core) {
    const fail = () => {
      setLayoutStatus(null);
      setError("Layout failed");
    };
    // The types view is an ER diagram and has its own layout: the skeleton
    // first, then each owner's attributes round it in their chosen order.
    // A layered layout would put the attributes in a column to one side.
    // The optimization view is a flow -- sets, then the variables and
    // parameters they index, then the rules that read those, then the
    // objective -- and its edges point that way, so a layered layout run left
    // to right sets the columns out in the order the model is read.
    if (isModel) {
      try {
        const lay: any = cy.layout(MODEL_LAYOUT as any);
        lay.on?.("layoutstart", () => setLayoutStatus("Laying out…"));
        lay.on?.("layoutstop", () => {
          setLayoutStatus(null);
          cy.fit(undefined, 30);
          if (cy.zoom() > 1.1) {
            cy.zoom(1.1);
            cy.center();
          }
        });
        Promise.resolve(lay.run()).catch(fail);
      } catch {
        fail();
      }
      return;
    }
    if (isTypes) {
      setLayoutStatus("Laying out…");
      // Through a promise, so a synchronous throw inside the layout lands in
      // `fail` like an asynchronous one rather than escaping the effect.
      Promise.resolve()
        .then(() => runErLayout(cy))
        .then(() => setLayoutStatus(null))
        .catch(fail);
      return;
    }
    const runGridFallback = () => {
      setLayoutStatus("ELK layout produced no positions — showing a grid");
      try {
         
        (cy.layout(GRID_LAYOUT as any) as any)?.run?.();
      } catch {
        // Nothing more we can do -- leave the note above visible so the user knows why the
        // canvas looks the way it does, rather than pretending the layout succeeded.
      }
    };
    try {
       
      const lay: any = cy.layout(ELK_LAYOUT as any);
      lay.on?.("layoutstart", () => setLayoutStatus("Laying out…"));
      lay.on?.("layoutstop", () => {
        setLayoutStatus(null);
        // A layout that "succeeds" but leaves every node stacked on the same point (e.g. a
        // shared-position-object bug, or ELK genuinely failing to produce output for some
        // graph) is worse than no layout at all -- detect it and fall back to a plain grid
        // rather than leaving the user staring at one dot.
         
        const nodesColl: any = (cy as any).nodes?.();
        const positions =
          nodesColl && typeof nodesColl.map === "function"
            ? nodesColl.map((n: any) => n.position())
            : [];
        if (positionsAreDegenerate(positions)) {
          runGridFallback();
        }
      });
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
     
    (cy as any).autoungrabify?.(next);
  }

  // H-1: node ids ordered left-to-right, then top-to-bottom by current on-canvas position, so
  // Arrow-key traversal is predictable. Recomputed from the live `cy` instance on every
  // keypress rather than cached, so it stays correct after nodes are added/removed/relaid-out.
  //
  // **Hidden nodes are not in it.** The filter effect above sets `display: none` on every node
  // a type checkbox, the search box or an expression excluded, and until this round the arrow
  // keys walked those too: with 1 of 23 nodes showing, a keyboard user was announced the other
  // 22 by name, the canvas panned to empty space, and Enter opened an editable panel -- with a
  // Delete button -- for a node that was not on the screen. A filtered graph gave keyboard
  // users a different set of nodes from the one sighted users could see, which is the sharper
  // version of the "0 axe violations" observation in the ledger: the number was true and the
  // inference drawn from it was not.
  //
  // `display` is read from cytoscape rather than re-derived from `filter`, because cytoscape
  // is what actually decides what is painted -- and the three filters already funnel into this
  // one property precisely so that everything downstream can ask one question.
  function orderedNodeIds(cy: Core): string[] {
     
    const nodesColl: any = (cy as any).nodes?.();
    const items: { id: string; x: number; y: number }[] =
      nodesColl && typeof nodesColl.map === "function"
        ? nodesColl
            .map((n: any) => {
              const pos = typeof n.position === "function" ? n.position() : undefined;
              const display = typeof n.style === "function" ? n.style("display") : undefined;
              // An attribute ellipse is not a stop: it describes its owner,
              // whose panel lists it, and stopping on each of forty would
              // bury the rectangles and diamonds between them.
              const decoration = typeof n.data === "function" && n.data("er") === "attribute";
              return { id: n.id(), x: pos?.x ?? 0, y: pos?.y ?? 0, hidden: display === "none" || decoration };
            })
            .filter((item: { hidden: boolean }) => !item.hidden)
        : [];
    items.sort((a, b) => a.x - b.x || a.y - b.y);
    return items.map((item) => item.id);
  }

  // H-1: moves the roving keyboard selection to `id` -- clears the previous node's `.kb-focus`
  // ring, applies it to the new one, centres the viewport on it, and updates the live region so
  // a screen-reader user knows where focus landed.
  function focusNode(id: string) {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
     
    const anyCy = cy as any;
    if (focusedNodeId && focusedNodeId !== id) {
      anyCy.getElementById?.(focusedNodeId)?.removeClass?.("kb-focus");
    }
    if (focusedEdgeCyId) {
      anyCy.getElementById?.(focusedEdgeCyId)?.removeClass?.("kb-focus");
      setFocusedEdgeCyId(null);
    }
    const node = anyCy.getElementById?.(id);
    node?.addClass?.("kb-focus");
    anyCy.center?.(node);
    setFocusedNodeId(id);
    const label = node?.data?.("label");
    setLiveMessage(typeof label === "string" && label ? label : id);
  }

  function focusEdge(cyId: string) {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
     
    const anyCy = cy as any;
    if (focusedNodeId) {
      anyCy.getElementById?.(focusedNodeId)?.removeClass?.("kb-focus");
    }
    if (focusedEdgeCyId && focusedEdgeCyId !== cyId) {
      anyCy.getElementById?.(focusedEdgeCyId)?.removeClass?.("kb-focus");
    }
    const edge = anyCy.getElementById?.(cyId);
    edge?.addClass?.("kb-focus");
    anyCy.center?.(edge);
    setFocusedEdgeCyId(cyId);
    const label = edge?.data?.("label");
    setLiveMessage(
      typeof label === "string" && label ? `${label} relationship` : "relationship"
    );
  }

  function incidentEdgeIds(cy: Core, nodeId: string): string[] {
     
    const edgesColl: any = (cy as any).edges?.();
    const ids: string[] = [];
    edgesColl?.forEach?.((edge: any) => {
      const display = typeof edge.style === "function" ? edge.style("display") : undefined;
      if (display === "none") {
        return;
      }
      const data = typeof edge.data === "function" ? edge.data() : undefined;
      if (data?.source === nodeId || data?.target === nodeId) {
        ids.push(edge.id());
      }
    });
    return ids;
  }

  function moveFocus(direction: 1 | -1) {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    const ids = orderedNodeIds(cy);
    if (ids.length === 0) {
      return;
    }
    const currentIndex = focusedNodeId ? ids.indexOf(focusedNodeId) : -1;
    const nextIndex =
      currentIndex === -1
        ? direction === 1
          ? 0
          : ids.length - 1
        : Math.min(ids.length - 1, Math.max(0, currentIndex + direction));
    focusNode(ids[nextIndex]);
  }

  function startKeyboardConnect() {
    if (!canEdit || !isObjects) {
      return;
    }
    const cy = cyRef.current;
    if (!focusedNodeId || !cy || !orderedNodeIds(cy).includes(focusedNodeId)) {
      setLiveMessage("Move to a node first");
      return;
    }
    setConnectFromId(focusedNodeId);
    const label = nodeLabelOf(focusedNodeId);
    setLiveMessage(`Connecting from ${label}. Move to the other node and press Enter.`);
  }

  function cycleIncidentEdge() {
    const cy = cyRef.current;
    if (!focusedNodeId || !cy || !orderedNodeIds(cy).includes(focusedNodeId)) {
      return;
    }
    const ids = incidentEdgeIds(cy, focusedNodeId);
    if (ids.length === 0) {
      setLiveMessage("No relationships on this node");
      return;
    }
    const current = focusedEdgeCyId ? ids.indexOf(focusedEdgeCyId) : -1;
    focusEdge(ids[(current + 1) % ids.length]);
  }

  function collapseFocused() {
    if (!nesting || !data || !focusedNodeId) return;
    const hidden = descendantIds(data.nodes, focusedNodeId);
    if (hidden.length === 0) {
      setLiveMessage("Nothing sits under this node");
      return;
    }
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      next.add(focusedNodeId);
      return next;
    });
    setLiveMessage(`Hid ${hidden.length} under ${nodeLabelOf(focusedNodeId)}`);
  }

  function expandFocused() {
    if (!nesting || !focusedNodeId) return;
    if (!collapsedIds.has(focusedNodeId)) {
      setLiveMessage("Nothing is hidden under this node");
      return;
    }
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      next.delete(focusedNodeId);
      return next;
    });
    setLiveMessage(`Showing children of ${nodeLabelOf(focusedNodeId)}`);
  }

  function collapseAll() {
    if (!nesting || !data) return;
    setCollapsedIds(new Set(parentIds(data.nodes)));
  }

  function expandAll() {
    if (!nesting) return;
    setCollapsedIds(new Set());
  }

  // Arrow keys move the roving selection, Enter opens the property panel,
  // C then Enter on another node creates a relationship, E then Enter
  // opens one so it can be deleted, Minus / Equals collapse a nest, and
  // Escape unwinds that path before leaving the canvas.
  function handleCanvasKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        moveFocus(1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        moveFocus(-1);
        break;
      case "Enter": {
        event.preventDefault();
        const cy = cyRef.current;
        if (focusedEdgeCyId && cy) {
           
          const edge = (cy as any).getElementById?.(focusedEdgeCyId);
          const graphId = edge?.data?.("graphId") ?? focusedEdgeCyId;
          onSelectionChangeRef.current?.({ kind: "edge", id: String(graphId) });
          break;
        }
        if (
          connectFromId &&
          focusedNodeId &&
          cy &&
          orderedNodeIds(cy).includes(focusedNodeId)
        ) {
          if (focusedNodeId === connectFromId) {
            setLiveMessage("Pick a different node to connect to");
            break;
          }
          setPendingEdge({ sourceId: connectFromId, targetId: focusedNodeId });
          setConnectFromId(null);
          break;
        }
        if (focusedNodeId && cy && orderedNodeIds(cy).includes(focusedNodeId)) {
          // What a tap on it would select: a diamond opens its relationship
          // type, as the edge it replaced did.
          const element = (cy as any).getElementById?.(focusedNodeId);
          onSelectionChangeRef.current?.(
            element && element.length !== 0 ? selectionOf(element, "node") : { kind: "node", id: focusedNodeId }
          );
        }
        break;
      }
      case "Escape":
        event.preventDefault();
        if (connectFromId) {
          setConnectFromId(null);
          setLiveMessage("Connect cancelled");
          break;
        }
        if (focusedEdgeCyId && focusedNodeId) {
          focusNode(focusedNodeId);
          break;
        }
        firstControlRef.current?.focus();
        break;
      case "c":
      case "C":
        event.preventDefault();
        startKeyboardConnect();
        break;
      case "e":
      case "E":
        event.preventDefault();
        cycleIncidentEdge();
        break;
      case "-":
      case "_":
        event.preventDefault();
        collapseFocused();
        break;
      case "=":
      case "+":
        event.preventDefault();
        expandFocused();
        break;
      default:
        break;
    }
  }

  function nodeEntityType(entityId: string): string | undefined {
    return data?.nodes.find((n) => n.id === entityId)?.type;
  }

  /** What the canvas draws this node as. Used to name the two ends of a
   * connect gesture: the rule is about entity TYPES, but the user dragged
   * between two named things and those are what they are looking at. */
  function nodeLabelOf(entityId: string): string {
    return data?.nodes.find((n) => n.id === entityId)?.label ?? `#${entityId}`;
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
    const relationshipTypeName =
      data?.relationship_types.find((rt) => rt.id === relationshipTypeId)?.name ?? "Relationship";
    createRelationship.mutate(
      {
        relationship_type_id: Number(relationshipTypeId),
        // from -> to is the direction the cardinality, type and cycle rules
        // are judged in; for a hierarchy, `from` is the parent.
        from_entity_id: Number(pendingEdge.sourceId),
        to_entity_id: Number(pendingEdge.targetId),
      },
      {
        onSuccess: () => toast.success(`${relationshipTypeName} created`),
        // A cardinality, cycle or type_mismatch 422 names the relationship
        // TYPE in `loc`, not a body field -- see relationshipErrorMessage.
        onError: (e) => setError(relationshipErrorMessage(e)),
      }
    );
    setPendingEdge(null);
  }

  async function handleCreateNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (createTypeId === "") {
      return;
    }
    const next: FieldErrors = {};
    const key = createKey.trim();
    // Client-side copy of 0009's `entity_key_not_blank` CHECK (API 422 on
    // `key`); the key is what model expressions address the entity by.
    if (key === "") {
      next.key = "Key: a key is required -- it is how model expressions refer to this entity.";
    }
    const built = buildAttrs(createAttributes, createDrafts);
    if (!built.ok) {
      Object.assign(next, built.errors);
    }
    setCreateErrors(next);
    if (Object.keys(next).length > 0) {
      return;
    }

    let created;
    try {
      created = await createEntity.mutateAsync({
        entity_type_id: createTypeId,
        key,
        label: createLabel.trim() === "" ? null : createLabel,
        // Every value is built from the definitions, so an omitted control
        // sends no key at all and the trigger materialises the default.
        attrs: built.ok ? built.attrs : {},
      });
    } catch (err) {
      const result = entityServerErrors(err, createAttributes.map((attribute) => attribute.name));
      setCreateErrors(result.fields);
      setError(result.general);
      return;
    }

    // Placing the node under a parent is a second write: in v1 the nesting IS
    // a relationship of the selected hierarchy type, read as from_entity =
    // parent of to_entity. There is no combined endpoint, so the entity
    // exists even if this half fails -- which the message has to say.
    if (hierarchyTypeId !== null && createParentId !== "") {
      try {
        await createRelationship.mutateAsync({
          relationship_type_id: hierarchyTypeId,
          from_entity_id: Number(createParentId),
          to_entity_id: created.id,
        });
      } catch (err) {
        setError(
          `${created.label ?? created.key} was created, but could not be placed under the chosen parent: ` +
            relationshipErrorMessage(err)
        );
        setShowCreateNode(false);
        resetCreateNodeForm();
        return;
      }
    }

    toast.success(`${created.label ?? created.key} created`);
    setShowCreateNode(false);
    resetCreateNodeForm();
  }

  return (
    // Carried forward from Task 8: fills whatever height its flex-column
    // parent (GraphDemo) hands it, and hands the remainder down to the
    // canvas via the flex-1/min-h-0 pair below -- see the cytoscape
    // container's comment for why this replaced a `100vh - 320px` guess.
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {isObjects && (
<select
            ref={firstControlRef as React.RefObject<HTMLSelectElement>}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            value={hierarchyTypeId ?? ""}
            onChange={(e) => onHierarchyTypeChange(e.target.value === "" ? null : Number(e.target.value))}
            title="Nest nodes under a hierarchy"
            aria-label="Hierarchy nesting"
            data-testid="hierarchy-select"
          >
            <option value="">No hierarchy nesting</option>
            {/* One `relationship_type` per option, filtered to is_hierarchy by
                the server. Its name, once: v1 has a single name per type. */}
            {hierarchyTypes.data?.items.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
        )}
        {/* The view toggle. Two buttons rather than a select, because the
            choice is between two named views and both should be one key or
            one click away; `aria-pressed` is what tells assistive tech which
            one is showing, and the live region below announces the switch. */}
        <div
          role="group"
          aria-label="Graph view"
          className="flex overflow-hidden rounded-md border border-slate-300"
          data-testid="graph-mode-toggle"
        >
          {VIEW_ORDER.map((candidate, index) => (
            <button
              key={candidate}
              // Outside the entity graph the hierarchy select is not rendered,
              // so the toggle's first button is the toolbar's first control.
              ref={
                !isObjects && index === 0
                  ? (firstControlRef as React.RefObject<HTMLButtonElement>)
                  : undefined
              }
              type="button"
              onClick={() => onModeChange(candidate)}
              aria-pressed={mode === candidate}
              title={VIEW_TITLE[candidate]}
              className={`px-2 py-1 text-sm ${
                mode === candidate ? "bg-slate-900 text-white" : "bg-white text-slate-700"
              }`}
              data-testid={`graph-mode-${candidate}`}
            >
              {VIEW_NAME[candidate]}
            </button>
          ))}
        </div>
        {isModel && modelTarget && (
          <ModelPicker target={modelTarget} onChange={(request) => onModelTargetChange?.(request)} />
        )}
        <button
          onClick={runLayout}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          type="button"
          title="Re-run automatic layout"
          aria-label="Re-run automatic layout"
        >
          Layout
        </button>
        <button
          onClick={fit}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          type="button"
          title="Fit the whole graph in view"
          aria-label="Fit the whole graph in view"
        >
          Fit
        </button>
        {nesting && (
          <>
            <button
              type="button"
              onClick={collapseAll}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
              title="Hide every nested node, leaving each parent on the canvas"
              data-testid="collapse-all"
            >
              Collapse all
            </button>
            <button
              type="button"
              onClick={expandAll}
              disabled={collapsedIds.size === 0}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              title="Show every node the current collapse hid"
              data-testid="expand-all"
            >
              Expand all
            </button>
          </>
        )}
        {/* Both of these write `entity` / `relationship` ROWS, which the
            schema view has none of: creating an entity type or a
            relationship type is a different form on a different page. */}
        {isObjects && canEdit && (
        <>
        <button
          type="button"
          onClick={toggleConnect}
          className={`rounded-md border px-2 py-1 text-sm ${
            connecting ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-300"
          }`}
          title={
            connecting
              ? "Connect mode is on -- drag from one node to another, or with a node focused press C then Enter on the other node"
              : "Turn on Connect and drag, or with a node focused press C then Enter on another node"
          }
          aria-pressed={connecting}
          data-testid="toggle-connect"
        >
          {connecting ? "Connecting: drag from one node to another" : "Connect"}
        </button>
        <button
          ref={createNodeToggleRef}
          type="button"
          onClick={() => {
            setShowCreateNode((v) => !v);
            resetCreateNodeForm();
          }}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          title="Create a new node"
          aria-expanded={showCreateNode}
          aria-controls="create-node-form"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
        </>
        )}
        {layoutStatus && (
          <span data-testid="layout-status" className="text-xs text-slate-500">
            {layoutStatus}
          </span>
        )}
      </div>

      {/* F-2/A-6: nothing else on the page explains how the canvas works -- boxes group nodes
          by hierarchy, arrows show relationship direction, and drag-to-connect only works once
          Connect mode is switched on. The text swaps to a focused instruction the moment Connect
          mode is actually on, so the mode is self-explanatory rather than a mystery toggle. */}
      <p data-testid="graph-help" className="mb-2 text-xs text-slate-500">
        {isModel
          ? "This is the problem's optimization model, read left to right: the sets it ranges over, the variables it decides and the parameters it reads, the rules that constrain them, and the objective. A dark hexagon must hold; an amber, dashed one may bend at the price shown. Click any part to see it written out."
          : isTypes
          ? "This is the domain's schema as an entity-relationship diagram: a rectangle per entity type, a diamond per relationship type with its cardinality at each end (1, n, m), and an ellipse per attribute in its chosen order. The underlined key is what a model addresses an entity by; a double-bordered diamond is a hierarchy. Click a rectangle or diamond to see and colour it."
          : connecting
            ? "Drag from one node to another to connect them, or with a node focused press C then Enter on the other node."
            : canEdit
              ? "Boxes group nodes by hierarchy; arrows show relationship direction. Click a node or edge to edit it. With a node focused, C then Enter on another node connects them; E then Enter opens a relationship to delete it." +
                (nesting ? " Minus hides a focused parent's children; Equals shows them." : "")
              : "Boxes group nodes by hierarchy; arrows show relationship direction. Click a node or edge to inspect it. With a node focused, E then Enter opens a relationship." +
                (nesting ? " Minus hides a focused parent's children; Equals shows them." : "")}
      </p>

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

      {showCreateNode && data && isObjects && canEdit && (
        <form
          id="create-node-form"
          onSubmit={handleCreateNode}
          onKeyDown={handleCreateNodeFormKeyDown}
          className="mb-2 space-y-3 rounded-md border border-slate-200 p-2"
          data-testid="create-node-form"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <FieldLabel htmlFor={`${createFormId}-type`} required>
                Entity type
              </FieldLabel>
              <select
                id={`${createFormId}-type`}
                required
                value={createTypeId}
                onChange={(e) => {
                  setCreateTypeId(e.target.value === "" ? "" : Number(e.target.value));
                  // Drafts belong to the previous type's attributes; keeping
                  // them would carry a value across to an unrelated name.
                  setCreateDrafts({});
                  setCreateErrors({});
                }}
                className={INPUT_CLASS}
              >
                <option value="">—</option>
                {/* The type's name, once: v1 has one name per entity type. */}
                {entityTypes.data?.items.map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel htmlFor={`${createFormId}-key`} required>
                Key
              </FieldLabel>
              <input
                id={`${createFormId}-key`}
                className={INPUT_CLASS}
                value={createKey}
                onChange={(e) => setCreateKey(e.target.value)}
                aria-invalid={createErrors.key ? "true" : undefined}
                aria-describedby={createErrors.key ? `${createFormId}-key-error` : undefined}
                autoComplete="off"
              />
              <FieldError id={`${createFormId}-key-error`} message={createErrors.key} />
            </div>
            <div>
              <FieldLabel htmlFor={`${createFormId}-label`}>Label</FieldLabel>
              <input
                id={`${createFormId}-label`}
                className={INPUT_CLASS}
                value={createLabel}
                onChange={(e) => setCreateLabel(e.target.value)}
                autoComplete="off"
              />
            </div>
          </div>
          {createTypeId !== "" && (
            <AttrsForm
              attributes={createAttributes}
              drafts={createDrafts}
              errors={createErrors}
              onChange={(name, value) => setCreateDrafts((prev) => ({ ...prev, [name]: value }))}
            />
          )}
          {hierarchyTypeId !== null && (
            <div className="sm:max-w-xs">
              <FieldLabel htmlFor={`${createFormId}-parent`}>Parent</FieldLabel>
              <select
                id={`${createFormId}-parent`}
                value={createParentId}
                onChange={(e) => setCreateParentId(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="">(no parent)</option>
                {data.nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">
                Places the new node under this one, as a relationship of the selected hierarchy.
              </p>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={createEntity.isPending || createRelationship.isPending}
              className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {createEntity.isPending ? "Creating…" : "Create"}
            </button>
            {/* H-9: was 20px tall with no padding -- px-2 py-1 clears the 24px Target Size floor. */}
            <button type="button" onClick={closeCreateNodeForm} className="rounded px-2 py-1 text-sm text-slate-500">
              Cancel
            </button>
          </div>
        </form>
      )}

      {connectNote && (
        <p
          data-testid="connect-note"
          className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
        >
          {connectNote}
        </p>
      )}

      {pendingEdge &&
        data &&
        isObjects &&
        (() => {
          const validTypes = validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId);
          // A node's `type` IS the entity type's name in v1, so there is
          // nothing to look up to name it.
          const fromType = nodeEntityType(pendingEdge.sourceId) ?? "?";
          const toType = nodeEntityType(pendingEdge.targetId) ?? "?";

          /*
           * Two entity types nothing joins is not a failed choice, it is a
           * refusal, so it is not dressed as one. It used to render inside
           * a box headed "Choose a relationship type:" as a grey line under
           * an empty list of buttons -- and on the drag that produced it in
           * the wild, nothing appeared at all (see the `ehcancel` handler).
           * It names the TYPES, because the rule is about types, and the two
           * entities the user was actually looking at; and it says where the
           * missing type is made, because otherwise the reader is told only
           * that they cannot do what they just tried.
           */
          if (validTypes.length === 0) {
            return (
              <div
                className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                data-testid="connect-refusal"
              >
                <p>
                  No relationship type joins {fromType} to {toType}, so &ldquo;
                  {nodeLabelOf(pendingEdge.sourceId)}&rdquo; cannot be connected to &ldquo;
                  {nodeLabelOf(pendingEdge.targetId)}&rdquo;.
                </p>
                <p className="mt-1">
                  Define one on the{" "}
                  <Link to="/relationship-types" className="inline-block rounded underline">
                    relationship types page
                  </Link>{" "}
                  — from {fromType} to {toType} — then connect them again.
                </p>
                <button
                  type="button"
                  onClick={() => setPendingEdge(null)}
                  className="mt-1 rounded px-2 py-1 text-sm text-amber-900 underline"
                >
                  Close
                </button>
              </div>
            );
          }

          return (
            <div className="mb-2 rounded-md border border-slate-200 p-2" data-testid="edge-type-picker">
              <p className="mb-1 text-xs text-slate-600">
                Choose a relationship type, from &ldquo;{nodeLabelOf(pendingEdge.sourceId)}&rdquo; to &ldquo;
                {nodeLabelOf(pendingEdge.targetId)}&rdquo;:
              </p>
              {/* v0 grouped "any -> any" types after a divider. v1 has none:
                  `from_type_id`/`to_type_id` are NOT NULL, so every
                  relationship type names both ends and the group could
                  never be non-empty. */}
              {validTypes.map((rt: RelationshipTypeOption) => (
                <button
                  key={rt.id}
                  type="button"
                  onClick={() => handleConfirmEdge(rt.id)}
                  disabled={createRelationship.isPending}
                  className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {rt.name}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setPendingEdge(null)}
                className="rounded px-2 py-1 text-sm text-slate-500"
              >
                Cancel
              </button>
            </div>
          );
        })()}

      {isOffline && <OfflineNotice subject="The graph" />}
      {!isOffline && isLoading && <p className="text-sm text-slate-500">Loading graph…</p>}
      {!isOffline && Boolean(loadError) && (
        <div className="mb-2 flex items-center gap-3 text-sm text-red-600">
          <p>Failed to load graph</p>
          <button
            type="button"
            onClick={() => refetchGraph()}
            className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            Retry
          </button>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        {/* Cytoscape caches this container's bounding rect when the instance is created (and
            otherwise only recomputes it on its own triggers), so if the page scrolls afterward --
            or in a headless/automated browser test that scrolls or resizes the window after mount
            -- rendered node positions and hit-testing (tap/drag) go stale against the old rect.
            Call cy.resize() before relying on them in that situation.
            F-4, revised: sized to fill whatever space flexbox leaves after the toolbar/banners
            above it (with a floor so a short window doesn't collapse it), instead of the fixed
            600px this replaced originally, or the `100vh - 320px` guess that replaced *that* --
            320 was a static assumption about how tall the chrome above the canvas would be, but
            at narrow widths the toolbar wraps onto many lines and blew right past it, starting
            the canvas ~800px down the page. `h-full` here (with `flex-1 min-h-0` on this parent
            and every ancestor up to GraphDemo's own flex column) derives the real remaining
            height from the DOM on every render instead of assuming one. */}
        <div
          ref={containerRef}
          data-testid="cytoscape-container"
          className="h-full min-h-[420px] w-full"
          tabIndex={0}
          // T11: a bare <div> has the implicit role `generic`, which prohibits
          // `aria-label` -- axe flagged this as `aria-prohibited-attr` (serious)
          // on every graph page state, so the name below was being discarded.
          // `application` is also what makes the arrow-key roving selection this
          // label advertises actually reachable: without it a screen reader stays
          // in browse mode and swallows the arrow keys before `onKeyDown` sees them.
          role="application"
          // The count is what is SHOWN, not what was loaded. It used to be
          // `data.nodes.length`, so a canvas displaying 1 of 23 nodes
          // announced itself as having 23 -- and the arrow keys, which this
          // very label advertises, then walked all 23. Both halves of that
          // are fixed; this is the half a screen-reader user hears first.
          aria-label={canvasLabel}
          onKeyDown={handleCanvasKeyDown}
        />
        {/* H-1: a polite live region announcing the label of whichever node keyboard focus is
            currently on, so a screen-reader user knows where the roving selection landed. Visually
            hidden (sr-only) -- its content is for assistive tech, not sighted users. */}
        <div data-testid="graph-live" aria-live="polite" className="sr-only">
          {liveMessage}
        </div>
        {/* A-6: with no nodes at all, the canvas was just an empty rectangle under the toolbar
            with nothing explaining why -- this overlay names the state and gives the one action
            that gets out of it. */}
        {!isLoading && !loadError && data && data.nodes.length === 0 && (
          <div
            data-testid="graph-empty-state"
            className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 text-center text-sm text-slate-500"
          >
            <p>
              {isModel
                ? modelTarget && modelTarget.problems.length === 0
                  ? "No problems in this domain yet, so there is no model to draw."
                  : "This problem has no model version yet."
                : isTypes
                  ? "No entity types in this domain yet."
                  : "No nodes yet."}
            </p>
            {isModel ? (
              <Link
                to="/model"
                className="pointer-events-auto rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
              >
                Open the model editor
              </Link>
            ) : isTypes ? (
              // The schema view has nothing to create from here: a type is
              // defined with its attributes, on its own page.
              <Link
                to="/entity-types"
                className="pointer-events-auto rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
              >
                Define the first entity type
              </Link>
            ) : canEdit ? (
              <button
                type="button"
                onClick={openCreateNodeForm}
                className="pointer-events-auto rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
              >
                Create the first node
              </button>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
