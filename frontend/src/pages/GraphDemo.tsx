import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import GraphEditor from "../components/GraphEditor";
import PropertyPanel from "../components/PropertyPanel";
import FilterBar, { DEFAULT_FILTER_STATE, deriveFilterCriteria } from "../components/FilterBar";
import type { FilterState } from "../components/FilterBar";
import { useGraphView } from "../api/graph";
import { useEntityTypes, type Id } from "../api/v1";
import { isEmptyDocument, type ExpressionDocument } from "../expressions/document";
import { withoutUntouchedRules } from "../expressions/defaults";
import { graphCatalogue, matchingNodeIds } from "../expressions/graphFilter";
import { validateExpression } from "../expressions/validate";
import { useDomain } from "../hooks/useDomain";
import { parseGraphMode, useGraphMode } from "../hooks/useGraphMode";
import { parseRouteId } from "../lib/routeId";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { GraphMode } from "../lib/typesGraph";

/**
 * One domain's entities and relationships, drawn.
 *
 * The scope is the domain chosen in the sidebar, like every other v1 screen
 * -- v0 scoped this page by `organization`, which schema v1 does not have.
 * The nesting is a `relationship_type` with `is_hierarchy = true`, chosen in
 * the canvas's own toolbar; without one the graph is drawn flat.
 *
 * Two views (Task 14b): **objects** -- the entities and relationships above
 * -- and **types**, the domain's schema. The choice lives in three places
 * on purpose, and they are not redundant:
 *
 * - `useGraphMode` persists it, so a reload comes back where you were;
 * - `?mode=types` makes a view **linkable**, and a link arriving with it
 *   wins over the stored choice and is then written through to it;
 * - the toggle in the canvas toolbar is what changes it.
 *
 * `?focus=` (Ruling 31's entity deep link) implies the objects view, since
 * the thing it focuses is an entity, and it is honoured even if `?mode=types`
 * is also present -- an entity link that landed on the schema would find
 * nothing.
 */

type Selection = { kind: "node" | "edge"; id: string } | null;

export default function GraphDemo() {
  useDocumentTitle("Domain Graph");
  const { domainId: selectedDomainId, setDomainId } = useDomain();
  // B-3: an entity page can deep-link here with `?focus=<entityId>` -- read
  // once on mount, not tracked reactively, since consuming the link clears it.
  const [searchParams, setSearchParams] = useSearchParams();
  // `?domain=<id>` travels with `focus` (the v1 successor of v0's `&org=`):
  // the entity may live in a domain other than the one selected, and the
  // focused node is only ever looked for in the loaded domain's graph. Read
  // once at mount and used *in place of* the selection until it has been
  // written through `setDomainId`, so the very first graph request already
  // targets the linked domain -- no wasted fetch of the old one.
  const [linkedDomainId, setLinkedDomainId] = useState<number | null>(() =>
    parseRouteId(searchParams.get("domain"))
  );
  const domainId = linkedDomainId ?? selectedDomainId;
  useEffect(() => {
    if (!searchParams.has("domain")) {
      return;
    }
    if (linkedDomainId !== null) {
      setDomainId(linkedDomainId);
      setLinkedDomainId(null);
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("domain");
        return next;
      },
      { replace: true }
    );
    // Mount-only, like `focus`: consuming the link clears it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // The view. Stored (survives a reload) and mirrored into the URL (so it
  // can be linked). A `?mode=` on arrival wins over the stored value; a
  // `?focus=` overrides both, because what it focuses is an entity.
  const { mode: storedMode, setMode: setStoredMode } = useGraphMode();
  const [linkedMode, setLinkedMode] = useState<GraphMode | null>(() => {
    if (searchParams.has("focus")) return "objects";
    return searchParams.has("mode") ? parseGraphMode(searchParams.get("mode")) : null;
  });
  const mode = linkedMode ?? storedMode;
  useEffect(() => {
    if (linkedMode !== null && linkedMode !== storedMode) {
      setStoredMode(linkedMode);
    }
    if (linkedMode !== null) {
      setLinkedMode(null);
    }
    // Mount-only, like `focus` and `domain`: consuming the link clears it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function changeMode(next: GraphMode) {
    setStoredMode(next);
    setLinkedMode(null);
    setSelection(null);
    setFilterState(DEFAULT_FILTER_STATE);
  }

  // Keep the URL showing the view, so the address bar is always a link to
  // what is on screen. `objects` is the default and leaves no parameter,
  // which keeps every existing link (and Ruling 31's `?focus=` one) intact.
  useEffect(() => {
    const current = searchParams.get("mode");
    const wanted = mode === "types" ? "types" : null;
    if (current === wanted) {
      return;
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (wanted === null) next.delete("mode");
        else next.set("mode", wanted);
        return next;
      },
      { replace: true }
    );
  }, [mode, searchParams, setSearchParams]);

  const [hierarchyTypeId, setHierarchyTypeId] = useState<Id | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  // Owned here (not inside FilterBar) so it survives GraphEditor's
  // hierarchy-driven data reload.
  const [filterState, setFilterState] = useState<FilterState>(DEFAULT_FILTER_STATE);
  // H-1 fix round 1: FilterBar's search box both filters and, on Enter,
  // selects the first matching node. `token` is a strictly-increasing counter
  // (not just the node id) so GraphEditor's roving-focus effect fires even
  // when the same node is searched for twice in a row.
  const [searchFocus, setSearchFocus] = useState<{ nodeId: string; token: number } | null>(null);
  const searchFocusTokenRef = useRef(0);

  const { data: graph } = useGraphView(domainId, hierarchyTypeId, mode);
  const selectedNodeId = selection?.kind === "node" ? selection.id : null;

  // Task 14c. The expression's FIELDS come from the entity types, because
  // the graph payload's `attribute_definitions` carry no `enum_values` and
  // no `required` -- this is the same query GraphEditor and PropertyPanel
  // already make, so React Query serves it once. The relationship types
  // for `count(...)` come out of the graph payload itself, which already
  // lists them, so the expression builder costs no extra request at all.
  const entityTypes = useEntityTypes(domainId, { limit: 500 }, { enabled: mode === "objects" });
  const expressionCatalogue = useMemo(
    () =>
      mode === "objects" && graph && entityTypes.data
        ? graphCatalogue(entityTypes.data.items, graph.relationship_types)
        : null,
    [mode, graph, entityTypes.data]
  );

  /**
   * The nodes the expression matches, or null for "no expression
   * constraint".
   *
   * Null for an EMPTY document and for an INVALID one alike: an expression
   * half-written must not blank the canvas. What is wrong with it is shown
   * in the builder, by the builder, from the same validator.
   *
   * A rule nobody has touched yet is taken out first
   * (`expressions/defaults.ts`). Pressing "+ Condition" used to cut this
   * canvas from 23 nodes to 2 before anything was typed, because the rule
   * the button creates is complete enough to evaluate.
   */
  const expressionMatchIds = useMemo(() => {
    if (!graph || !expressionCatalogue) {
      return null;
    }
    const document = withoutUntouchedRules(filterState.expression ?? null, expressionCatalogue);
    if (isEmptyDocument(document)) {
      return null;
    }
    const result = validateExpression(document as ExpressionDocument, expressionCatalogue);
    return result.valid ? matchingNodeIds(graph, expressionCatalogue, result.document) : null;
  }, [graph, expressionCatalogue, filterState.expression]);

  // B-3: consume a deep-link "focus" once its target shows up in the loaded
  // graph. Guarded by a ref (not just by clearing the URL param) so a graph
  // still loading -- or briefly missing the node mid-refetch -- isn't treated
  // as "not found".
  const consumedFocusRef = useRef(false);
  useEffect(() => {
    const focusEntityId = searchParams.get("focus");
    // A focus link names an ENTITY. Types-mode node ids are namespaced
    // (`type-<id>`) so one could never match, but being explicit keeps the
    // ref from being consumed by a graph that cannot hold the target.
    if (!focusEntityId || consumedFocusRef.current || !graph || mode !== "objects") {
      return;
    }
    const match = graph.nodes.find((node) => node.id === focusEntityId);
    if (!match) {
      return;
    }
    consumedFocusRef.current = true;
    setSelection({ kind: "node", id: match.id });
    searchFocusTokenRef.current += 1;
    setSearchFocus({ nodeId: match.id, token: searchFocusTokenRef.current });
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("focus");
        return next;
      },
      { replace: true }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, searchParams, mode]);

  // Memoized so GraphEditor's `[filter, data]` effect (which re-styles every
  // node/edge) only reruns when the criteria actually change.
  const filter = useMemo(
    () =>
      graph
        ? deriveFilterCriteria(filterState, selectedNodeId, graph.edges, expressionMatchIds)
        : undefined,
    [filterState, selectedNodeId, graph?.edges, expressionMatchIds]
  );

  // H-1 fix round 1: typing a node's label and pressing Enter selects it.
  // A v1 node's only text is its label (which already falls back to the
  // entity's key), so that is what is matched -- the same rule GraphEditor's
  // own filter applies.
  function handleSearchSubmit(query: string) {
    const q = query.trim().toLowerCase();
    if (!q || !graph) {
      return;
    }
    const match = graph.nodes.find((node) => node.label.toLowerCase().includes(q));
    if (!match) {
      return;
    }
    setSelection({ kind: "node", id: match.id });
    searchFocusTokenRef.current += 1;
    setSearchFocus({ nodeId: match.id, token: searchFocusTokenRef.current });
  }

  if (domainId === null) {
    return (
      <div className="max-w-2xl">
        <h1 className="mb-4 text-lg font-semibold text-slate-900">Domain Graph</h1>
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to draw its graph.
          </p>
          <p className="mt-1">
            No domain yet?{" "}
            <Link to="/public/domain" className="inline-block rounded py-1 text-blue-600 underline">
              Create one on the Domains page
            </Link>
            .
          </p>
        </div>
      </div>
    );
  }

  return (
    // F-4/carried-forward from Task 8: a flex column filling AppShell's
    // <main> (itself bounded to the viewport height), so the canvas derives
    // its height from actual layout instead of a `100vh - <guess>`
    // calculation. `min-h-0` lets this column shrink below its content's
    // natural height so the flex-1 row further down claims the rest.
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Domain Graph</h1>
      {graph && (
        <FilterBar
          entityTypes={graph.entity_types}
          selectedNodeId={selectedNodeId}
          value={filterState}
          onChange={setFilterState}
          onSubmitSearch={handleSearchSubmit}
          // The bar stays in both views, because search and
          // highlight-connections are just as useful on a schema. What it
          // groups by changes: a types node's `type` is its entity type's
          // ROLE, so the checkbox list offers the roles present. Filtering
          // types by their own names would only duplicate the search box.
          typeNoun={mode === "types" ? "Roles" : "Types"}
          searchLabel={
            mode === "types" ? "Search types by name" : "Search nodes by label"
          }
          // Only in the objects view: the fields are an entity's
          // attributes, and a types node IS an entity type, not an entity.
          expressionCatalogue={expressionCatalogue ?? undefined}
        />
      )}
      {/* F-1: below 1024px the property panel kept its own minimum width and
          squeezed the canvas to an unusable column. Stacking them keeps the
          canvas at full viewport width there. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row" data-testid="graph-layout">
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Keyed by domainId: a domain switch is rare and its graph is
              unrelated to the previous one, so the simplest correct fix is to
              rebuild the canvas rather than diff across domains. Hierarchy
              switches within a domain stay incremental. */}
          <GraphEditor
            key={domainId}
            domainId={domainId}
            mode={mode}
            onModeChange={changeMode}
            hierarchyTypeId={hierarchyTypeId}
            onHierarchyTypeChange={(id) => {
              setHierarchyTypeId(id);
              setSelection(null);
            }}
            filter={filter}
            onSelectionChange={setSelection}
            focusRequest={searchFocus}
          />
        </div>
        {/* F-5: `self-start` keeps this box only as tall as its own content
            instead of stretching to match the canvas beside it. */}
        <div className="w-full self-start rounded-md border border-slate-200 p-3 lg:w-72 lg:shrink-0">
          {graph && (
            <PropertyPanel
              key={selection ? `${selection.kind}-${selection.id}` : "none"}
              domainId={domainId}
              mode={mode}
              graph={graph}
              selection={selection}
              onClose={() => setSelection(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
