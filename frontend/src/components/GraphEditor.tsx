import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { useCreateEdge, useCreateNode, useGraph } from "../api/graph";
import { formatApiError } from "../api/errors";
import { AttributeInput, attributeValueFromForm, splitBuiltinCollisions } from "./attributeInputs";
import { useToast } from "./ToastProvider";
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

  // An edge whose source/target isn't among the nodes that will actually exist in cy (kept
  // existing ones + the ones we're about to add) can't be created -- real Cytoscape's cy.add()
  // throws synchronously ("Can not create edge ... with nonexistent source/target"), which would
  // abort the whole batch. Skip those rather than let a dangling edge take down the update.
  const validNodeIds = new Set(graph.nodes.map((n) => n.id));
  let skippedEdgeCount = 0;

  const newEdges: GraphEdge[] = [];
  desiredEdges.forEach((edge, id) => {
    if (existingEdgeIds.has(id)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ele = (cy as any).getElementById(id);
      ele.data({ label: edge.label, type: edge.type });
    } else if (!validNodeIds.has(edge.source) || !validNodeIds.has(edge.target)) {
      skippedEdgeCount += 1;
    } else {
      newEdges.push(edge);
    }
  });

  if (skippedEdgeCount > 0 && typeof console !== "undefined") {
    // eslint-disable-next-line no-console
    console.warn(`applyGraphToCy: skipped ${skippedEdgeCount} edge(s) referencing a missing node`);
  }

  if (newNodes.length > 0 || newEdges.length > 0) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const extent = (cy as any).extent?.() ?? { x1: 0, y1: 0, x2: 0, y2: 0 };
    const center = { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 };
    const elementsToAdd = [
      // Each new node gets its OWN position object -- cytoscape stores `position` by reference
      // (no clone) and later mutates it in place when the layout repositions a node, so nodes
      // that shared one `center` object would all keep reflecting whichever node's position was
      // set last, collapsing the whole graph onto a single point after layout.
      ...newNodes.map((node) => ({
        data: { id: node.id, label: node.label, type: node.type, parent: node.parent ?? undefined },
        position: { x: center.x, y: center.y },
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

const GRID_LAYOUT = { name: "grid" } as const;

/**
 * True when `positions` has 2+ points that are all within 1px of each other in both x and y --
 * i.e. a layout that computed distinct per-node results but somehow left every node stacked on
 * the same spot (see the `center`-object-sharing bug applyGraphToCy guards against above; kept
 * as a runtime safety net for any other cause, e.g. a genuine ELK failure).
 */
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
  organizationId,
  hierarchyId,
  onHierarchyChange,
  filter,
  onSelectionChange,
  focusRequest,
}: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ehRef = useRef<any>(null);
  const graphRef = useRef<GraphResponse | null>(null);
  const hasLaidOutRef = useRef(false);
  // The mount effect (below) registers cy event handlers exactly once, so they close over
  // whatever `onSelectionChange` was at that first render. Route through a ref, kept current on
  // every render, so a later render's new callback is the one actually invoked on tap.
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);
  const [createEntityTypeId, setCreateEntityTypeId] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [layoutStatus, setLayoutStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // H-1: the roving keyboard selection on the canvas -- which node last received Arrow-key
  // focus, and the text a polite live region announces as it moves. Derived fresh from the
  // live cytoscape instance at each keypress (see orderedNodeIds) rather than cached, so it
  // stays correct as nodes are added/removed/relaid-out.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [liveMessage, setLiveMessage] = useState("");
  // H-7: the create-node toggle is the trigger for the form below -- Escape inside the form
  // closes it and returns focus here, rather than dropping focus back to the document body.
  const createNodeToggleRef = useRef<HTMLButtonElement | null>(null);
  // H-1: Escape on the canvas returns focus to the toolbar's first control (the hierarchy
  // select) rather than dropping it back to the document body.
  const firstControlRef = useRef<HTMLSelectElement | null>(null);

  function closeCreateNodeForm() {
    setShowCreateNode(false);
    setCreateEntityTypeId("");
    createNodeToggleRef.current?.focus();
  }

  function openCreateNodeForm() {
    setShowCreateNode(true);
    setCreateEntityTypeId("");
  }

  function handleCreateNodeFormKeyDown(event: ReactKeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      closeCreateNodeForm();
    }
  }

  const { data, isLoading, error: loadError, refetch: refetchGraph } = useGraph(organizationId, hierarchyId);
  const createNode = useCreateNode(organizationId, hierarchyId);
  const createEdge = useCreateEdge(organizationId, hierarchyId);
  const toast = useToast();

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
            // F-3: the label used to match the node fill exactly (both #0f172a), so it was
            // legible only while it happened to sit above the circle -- any label drifting over
            // a neighbouring node's fill disappeared into it. A near-white label plus a dark
            // outline reads over both the light canvas background and any node's dark fill.
            color: "#f8fafc",
            "text-outline-width": 2,
            "text-outline-color": "#0f172a",
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
        // H-1: the visible ring for the node currently holding keyboard (roving) focus.
        { selector: ".kb-focus", style: { "border-width": 4, "border-color": "#f59e0b", "border-style": "solid" } },
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const eh = (cy as any).edgehandles({});
    ehRef.current = eh;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", "node", (evt: any) => {
      onSelectionChangeRef.current?.({ kind: "node", id: evt.target.id() });
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", "edge", (evt: any) => {
      onSelectionChangeRef.current?.({ kind: "edge", id: evt.target.id() });
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.on("tap", (evt: any) => {
      if (evt.target === cy) {
        onSelectionChangeRef.current?.(null);
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
    const { structureChanged } = applyGraphToCy(cy, data);
    graphRef.current = data;
    if (structureChanged || !hasLaidOutRef.current) {
      hasLaidOutRef.current = true;
      startLayout(cy);
    }
  }, [data, loadError]);

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

    cy.nodes().forEach((node) => {
      const graphNode = nodeById.get(node.id());
      if (!graphNode) {
        return;
      }
      const typeOk = selectedTypesSet === null || selectedTypesSet.has(graphNode.type);
      const codeValue = graphNode.attributes?.code;
      const searchOk =
        !searchLower ||
        graphNode.label.toLowerCase().includes(searchLower) ||
        (typeof codeValue === "string" && codeValue.toLowerCase().includes(searchLower));
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
    const runGridFallback = () => {
      setLayoutStatus("ELK layout produced no positions — showing a grid");
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (cy.layout(GRID_LAYOUT as any) as any)?.run?.();
      } catch {
        // Nothing more we can do -- leave the note above visible so the user knows why the
        // canvas looks the way it does, rather than pretending the layout succeeded.
      }
    };
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const lay: any = cy.layout(ELK_LAYOUT as any);
      lay.on?.("layoutstart", () => setLayoutStatus("Laying out…"));
      lay.on?.("layoutstop", () => {
        setLayoutStatus(null);
        // A layout that "succeeds" but leaves every node stacked on the same point (e.g. a
        // shared-position-object bug, or ELK genuinely failing to produce output for some
        // graph) is worse than no layout at all -- detect it and fall back to a plain grid
        // rather than leaving the user staring at one dot.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (cy as any).autoungrabify?.(next);
  }

  // H-1: node ids ordered left-to-right, then top-to-bottom by current on-canvas position, so
  // Arrow-key traversal is predictable. Recomputed from the live `cy` instance on every
  // keypress rather than cached, so it stays correct after nodes are added/removed/relaid-out.
  function orderedNodeIds(cy: Core): string[] {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodesColl: any = (cy as any).nodes?.();
    const items: { id: string; x: number; y: number }[] =
      nodesColl && typeof nodesColl.map === "function"
        ? nodesColl.map((n: any) => {
            const pos = typeof n.position === "function" ? n.position() : undefined;
            return { id: n.id(), x: pos?.x ?? 0, y: pos?.y ?? 0 };
          })
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const anyCy = cy as any;
    if (focusedNodeId && focusedNodeId !== id) {
      anyCy.getElementById?.(focusedNodeId)?.removeClass?.("kb-focus");
    }
    const node = anyCy.getElementById?.(id);
    node?.addClass?.("kb-focus");
    anyCy.center?.(node);
    setFocusedNodeId(id);
    const label = node?.data?.("label");
    setLiveMessage(typeof label === "string" && label ? label : id);
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

  // H-1: the canvas container's own keydown handler -- this is the keyboard path the graph
  // editor previously had none of at all (tabIndex was -1 and refused focus). Arrow keys move
  // the roving selection, Enter opens the property panel for the focused node via the same
  // onSelectionChange path a tap takes, and Escape returns focus to the toolbar. Creating an
  // edge by keyboard is explicitly out of scope -- that stays a pointer (drag) gesture.
  function handleCanvasKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
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
      case "Enter":
        event.preventDefault();
        if (focusedNodeId) {
          onSelectionChangeRef.current?.({ kind: "node", id: focusedNodeId });
        }
        break;
      case "Escape":
        event.preventDefault();
        firstControlRef.current?.focus();
        break;
      default:
        break;
    }
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
    const relationshipTypeName =
      data?.relationship_types.find((rt) => rt.id === relationshipTypeId)?.name ?? "Relationship";
    createEdge.mutate(
      {
        relationship_type_id: relationshipTypeId,
        source_entity_id: pendingEdge.sourceId,
        target_entity_id: pendingEdge.targetId,
      },
      {
        onSuccess: () => toast.success(`${relationshipTypeName} created`),
        onError: (e) => setError(formatApiError(e)),
      }
    );
    setPendingEdge(null);
  }

  function handleCreateNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const entityTypeId = String(form.get("entity_type_id") ?? "");
    const name = String(form.get("name") ?? "");
    const code = String(form.get("code") ?? "") || undefined;
    const parentEntityId = String(form.get("parent_entity_id") ?? "") || undefined;
    if (!entityTypeId || !name) {
      return;
    }
    // Attribute definitions that collide with a built-in field (code/status/
    // description/name) are hidden from the form and never sent -- see
    // splitBuiltinCollisions.
    const { visible: definitions } = splitBuiltinCollisions(
      data?.attribute_definitions.filter((d) => d.entity_type_id === entityTypeId) ?? []
    );
    const attributes: Record<string, unknown> = {};
    try {
      for (const def of definitions) {
        const value = attributeValueFromForm(form, def);
        if (value !== null) {
          attributes[def.code] = value;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid attribute value");
      return;
    }
    createNode.mutate(
      {
        organization_id: organizationId,
        entity_type_id: entityTypeId,
        name,
        code,
        attributes,
        hierarchy_id: hierarchyId ?? undefined,
        parent_entity_id: parentEntityId,
      },
      {
        onSuccess: () => toast.success(`${name} created`),
        onError: (e) => setError(formatApiError(e)),
      }
    );
    setShowCreateNode(false);
    setCreateEntityTypeId("");
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          ref={firstControlRef}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => onHierarchyChange(e.target.value || null)}
          title="Nest nodes under a hierarchy"
          aria-label="Hierarchy nesting"
          data-testid="hierarchy-select"
        >
          <option value="">No hierarchy nesting</option>
          {data?.hierarchies.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name} ({h.code})
            </option>
          ))}
        </select>
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
        <button
          type="button"
          onClick={toggleConnect}
          className={`rounded-md border px-2 py-1 text-sm ${
            connecting ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-300"
          }`}
          title={
            connecting
              ? "Connect mode is on -- drag from one node to another to create a relationship"
              : "Turn on Connect mode, then drag from one node to another to create a relationship"
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
            setCreateEntityTypeId("");
          }}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          title="Create a new node"
          aria-expanded={showCreateNode}
          aria-controls="create-node-form"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
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
        {connecting
          ? "Drag from one node to another to connect them."
          : "Boxes group nodes by hierarchy; arrows show relationship direction. Click a node or edge to edit it, or turn on Connect and drag between two nodes to create a relationship."}
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

      {showCreateNode && data && (
        <form
          id="create-node-form"
          onSubmit={handleCreateNode}
          onKeyDown={handleCreateNodeFormKeyDown}
          className="mb-2 flex flex-wrap items-end gap-2 rounded-md border border-slate-200 p-2"
          data-testid="create-node-form"
        >
          <label className="text-xs">
            Type
            <select
              name="entity_type_id"
              required
              value={createEntityTypeId}
              onChange={(e) => setCreateEntityTypeId(e.target.value)}
              className="block rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="">—</option>
              {data.entity_types.map((et) => (
                <option key={et.id} value={et.id}>
                  {et.name} ({et.code})
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
          {(() => {
            const { visible, hidden } = splitBuiltinCollisions(
              data.attribute_definitions.filter((def) => def.entity_type_id === createEntityTypeId)
            );
            return (
              <>
                {visible.map((def) => (
                  <label key={def.id} className="text-xs">
                    {def.name}
                    <AttributeInput def={def} />
                  </label>
                ))}
                {hidden.map((def) => (
                  <p key={def.id} className="basis-full text-xs text-slate-500">
                    attribute {def.code} hidden: collides with a built-in field
                  </p>
                ))}
              </>
            );
          })()}
          {hierarchyId && (
            <label className="text-xs">
              Parent (any node placed in this hierarchy will be used; others get an error)
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
          <button
            type="submit"
            disabled={createNode.isPending}
            className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {createNode.isPending ? "Creating…" : "Create"}
          </button>
          <button type="button" onClick={closeCreateNodeForm} className="text-sm text-slate-500">
            Cancel
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
            // Type-constrained matches (naming a specific source and/or target type) first,
            // since they're almost always what the user meant for this dragged pair; fully
            // unconstrained ("any -> any") types are the generic catch-alls, listed after a
            // divider so they read as a separate, lower-priority group.
            const constrained = validTypes.filter(
              (rt) => rt.source_entity_type !== null || rt.target_entity_type !== null
            );
            const unconstrained = validTypes.filter(
              (rt) => rt.source_entity_type === null && rt.target_entity_type === null
            );
            const button = (rt: RelationshipTypeOption) => (
              <button
                key={rt.id}
                type="button"
                onClick={() => handleConfirmEdge(rt.id)}
                disabled={createEdge.isPending}
                className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                {rt.name} ({rt.code})
              </button>
            );
            return (
              <>
                {constrained.map(button)}
                {constrained.length > 0 && unconstrained.length > 0 && (
                  <hr data-testid="picker-divider" className="my-1 border-slate-200" />
                )}
                {unconstrained.map(button)}
              </>
            );
          })()}
          <button type="button" onClick={() => setPendingEdge(null)} className="text-sm text-slate-500">
            Cancel
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-slate-500">Loading graph…</p>}
      {loadError && (
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
      <div className="relative">
        {/* Cytoscape caches this container's bounding rect when the instance is created (and
            otherwise only recomputes it on its own triggers), so if the page scrolls afterward --
            or in a headless/automated browser test that scrolls or resizes the window after mount
            -- rendered node positions and hit-testing (tap/drag) go stale against the old rect.
            Call cy.resize() before relying on them in that situation.
            F-4: sized to the available viewport height (with a floor so a short window doesn't
            collapse it) instead of a fixed 600px that either strands the canvas in a tiny column
            on a short screen or leaves a large empty band beneath it on a tall one. */}
        <div
          ref={containerRef}
          data-testid="cytoscape-container"
          className="h-[calc(100vh-320px)] min-h-[420px] w-full"
          tabIndex={0}
          aria-label={`Graph canvas, ${data?.nodes.length ?? 0} nodes — use the arrow keys to move between nodes`}
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
            <p>No nodes yet.</p>
            <button
              type="button"
              onClick={openCreateNodeForm}
              className="pointer-events-auto rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white"
            >
              Create the first node
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
