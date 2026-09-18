import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import GraphEditor from "../components/GraphEditor";
import OfflineNotice from "../components/OfflineNotice";
import PropertyPanel from "../components/PropertyPanel";
import FilterBar, { DEFAULT_FILTER_STATE, deriveFilterCriteria } from "../components/FilterBar";
import type { FilterState } from "../components/FilterBar";
import { useGraph } from "../api/graph";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

type Selection = { kind: "node" | "edge"; id: string } | null;

type Organization = { id: string; code: string; name: string };

function useOrganizations() {
  return useQuery({
    queryKey: ["organizations", "list"],
    queryFn: async () => {
      const result = await apiFetch<{ items: Organization[]; total: number }>(
        "/api/iam/organization/?limit=200&offset=0"
      );
      return [...result.items].sort((a, b) => a.name.localeCompare(b.name));
    },
  });
}

export default function GraphDemo() {
  useDocumentTitle("Domain Graph");
  const { data: organizations, isLoading: orgsLoading, fetchStatus: orgsFetchStatus } = useOrganizations();
  // D-7: this query gates the entire page -- everything below (including GraphEditor's own
  // offline handling) never even mounts until it resolves. Offline, it pauses rather than
  // failing, so without this the page would show "Loading organization…" forever.
  const orgsOffline = orgsFetchStatus === "paused" && !organizations;
  // B-3: a domain entity's detail page deep-links here with `?focus=<entityId>&org=<orgId>`
  // (see EntityDetail's "Open in graph" link) -- read once on mount, not tracked reactively,
  // since consuming the link below clears these params from the URL.
  const [searchParams, setSearchParams] = useSearchParams();
  // Only set once the user explicitly picks an org (or a deep link names one); the effective
  // organizationId below falls back to the org coded "default" (or the first org, alphabetically
  // by name) until then, so there's no separate effect-driven state update to initialize it.
  const [organizationOverride, setOrganizationOverride] = useState<string | null>(
    () => searchParams.get("org")
  );
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  // Owned here (not inside FilterBar) so it survives GraphEditor's hierarchy-driven data
  // reload and FilterBar no longer needs a remount key to "reset" on hierarchy switch.
  const [filterState, setFilterState] = useState<FilterState>(DEFAULT_FILTER_STATE);
  // H-1 fix round 1: the one search box on this page (FilterBar's) both filters (existing
  // behaviour, via filterState.search above) and, on Enter, selects the first matching node --
  // this used to be a documented keyboard workaround that selected nothing. `token` is a
  // strictly-increasing counter (not just the matched node id) so GraphEditor's roving-focus
  // effect fires even when the same node is searched for twice in a row.
  const [searchFocus, setSearchFocus] = useState<{ nodeId: string; token: number } | null>(null);
  const searchFocusTokenRef = useRef(0);

  const organizationId = useMemo(() => {
    if (!organizations || organizations.length === 0) {
      return null;
    }
    if (organizationOverride && organizations.some((org) => org.id === organizationOverride)) {
      return organizationOverride;
    }
    const defaultOrg = organizations.find((org) => org.code === "default") ?? organizations[0];
    return defaultOrg.id;
  }, [organizations, organizationOverride]);

  const { data: graph } = useGraph(organizationId ?? "", hierarchyId);
  const selectedNodeId = selection?.kind === "node" ? selection.id : null;

  // B-3: consume a deep-link "focus" once its target node shows up in the loaded graph --
  // selects it and routes it through the same searchFocus/focusRequest mechanism GraphEditor's
  // own roving-keyboard-focus and the in-page search box (handleSearchSubmit, below) already
  // use, rather than a second selection path. Guarded by a ref (not just clearing the URL
  // param) so a graph that's still loading -- or briefly missing the node mid-refetch -- doesn't
  // get treated as "not found" and silently drop the request before it's had a chance to arrive.
  const consumedFocusRef = useRef(false);
  useEffect(() => {
    const focusEntityId = searchParams.get("focus");
    if (!focusEntityId || consumedFocusRef.current || !graph) {
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
        next.delete("org");
        return next;
      },
      { replace: true }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, searchParams]);
  // Memoized so GraphEditor's `[filter, data]` effect (which re-styles every node/edge's
  // display/highlight classes) only reruns when the criteria actually change, not on every
  // GraphDemo render (e.g. a selection change unrelated to filtering) -- deriveFilterCriteria
  // returns a fresh object identity each call otherwise.
  const filter = useMemo(
    () => (graph ? deriveFilterCriteria(filterState, selectedNodeId, graph.edges) : undefined),
    [filterState, selectedNodeId, graph?.edges]
  );

  // H-1 fix round 1: the audit finding was about this exact search box -- typing a node's label
  // and pressing Enter selected nothing. Same case-insensitive label-or-code match GraphEditor's
  // own filter uses, first match in the graph's node order; a miss leaves the filter applied and
  // the selection untouched (no error, nothing cleared).
  function handleSearchSubmit(query: string) {
    const q = query.trim().toLowerCase();
    if (!q || !graph) {
      return;
    }
    const match = graph.nodes.find((node) => {
      const code = node.attributes?.code;
      return node.label.toLowerCase().includes(q) || (typeof code === "string" && code.toLowerCase().includes(q));
    });
    if (!match) {
      return;
    }
    setSelection({ kind: "node", id: match.id });
    searchFocusTokenRef.current += 1;
    setSearchFocus({ nodeId: match.id, token: searchFocusTokenRef.current });
  }

  function handleOrganizationChange(id: string) {
    setOrganizationOverride(id);
    setHierarchyId(null);
    setSelection(null);
    setFilterState(DEFAULT_FILTER_STATE);
    // GraphEditor is keyed by organization, so it remounts here and its
    // focus-request effect runs afresh. Left set, a search from the previous
    // organization would be replayed against a graph that has no such node.
    setSearchFocus(null);
  }

  if (orgsOffline) {
    return <OfflineNotice subject="The graph" />;
  }

  if (orgsLoading || !organizations) {
    return <p className="text-sm text-slate-500">Loading organization…</p>;
  }

  if (organizations.length === 0) {
    return <p className="text-sm text-slate-500">No organizations found. Create one to view the graph.</p>;
  }

  if (!organizationId) {
    return <p className="text-sm text-slate-500">Loading organization…</p>;
  }

  return (
    // F-4/carried-forward from Task 8: a flex column filling AppShell's
    // <main> (itself bounded to the viewport height -- see AppShell.tsx),
    // so the canvas below derives its height from actual layout instead of
    // a `100vh - <guessed chrome height>` calculation. `min-h-0` lets this
    // column shrink below its content's natural height so the flex-1 row
    // further down actually gets to claim the remaining space.
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Domain Graph</h1>
      <div className="mb-4">
        <label htmlFor="org-select" className="mb-1 block text-xs font-medium text-slate-600">
          Organization
        </label>
        <select
          id="org-select"
          data-testid="org-select"
          value={organizationId}
          onChange={(event) => handleOrganizationChange(event.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        >
          {organizations.map((org) => (
            <option key={org.id} value={org.id}>
              {`${org.name} (${org.code})`}
            </option>
          ))}
        </select>
      </div>
      {graph && (
        <FilterBar
          entityTypes={graph.entity_types}
          edges={graph.edges}
          selectedNodeId={selectedNodeId}
          value={filterState}
          onChange={setFilterState}
          onSubmitSearch={handleSearchSubmit}
        />
      )}
      {/* F-1: below 1024px (Tailwind's `lg` breakpoint) the property panel kept its own minimum
          width and refused to shrink, squeezing the canvas down to an unusable ~167px column.
          Stacking the panel under the canvas on narrow screens, instead of forcing them to share
          one row, keeps the canvas at the full viewport width there. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row" data-testid="graph-layout">
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Keyed by organizationId: an org switch is rare and its graph is unrelated to the
              previous one, so the simplest correct fix is to fully rebuild the canvas (a fresh
              cytoscape instance) rather than diff across organisations -- otherwise a failed or
              still-in-flight refetch after switching orgs could leave the previous org's nodes
              drawn and actionable. Hierarchy switches within the same org stay incremental, via
              GraphEditor's own diffing effect. */}
          <GraphEditor
            key={organizationId}
            organizationId={organizationId}
            hierarchyId={hierarchyId}
            onHierarchyChange={setHierarchyId}
            filter={filter}
            onSelectionChange={setSelection}
            focusRequest={searchFocus}
          />
        </div>
        {/* F-5: `self-start` keeps this box only as tall as its own content (a couple of lines
            when nothing is selected) instead of stretching to match the much taller canvas next
            to it in the flex row, which used to leave a large empty rectangle. */}
        <div className="w-full self-start rounded-md border border-slate-200 p-3 lg:w-72 lg:shrink-0">
          {graph && (
            <PropertyPanel
              key={selection ? `${selection.kind}-${selection.id}` : "none"}
              organizationId={organizationId}
              hierarchyId={hierarchyId}
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
