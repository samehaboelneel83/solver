import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import GraphEditor from "../components/GraphEditor";
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
  const { data: organizations, isLoading: orgsLoading } = useOrganizations();
  // Only set once the user explicitly picks an org; the effective organizationId below
  // falls back to the org coded "default" (or the first org, alphabetically by name) until
  // then, so there's no separate effect-driven state update to initialize it.
  const [organizationOverride, setOrganizationOverride] = useState<string | null>(null);
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  // Owned here (not inside FilterBar) so it survives GraphEditor's hierarchy-driven data
  // reload and FilterBar no longer needs a remount key to "reset" on hierarchy switch.
  const [filterState, setFilterState] = useState<FilterState>(DEFAULT_FILTER_STATE);

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
  // Memoized so GraphEditor's `[filter, data]` effect (which re-styles every node/edge's
  // display/highlight classes) only reruns when the criteria actually change, not on every
  // GraphDemo render (e.g. a selection change unrelated to filtering) -- deriveFilterCriteria
  // returns a fresh object identity each call otherwise.
  const filter = useMemo(
    () => (graph ? deriveFilterCriteria(filterState, selectedNodeId, graph.edges) : undefined),
    [filterState, selectedNodeId, graph?.edges]
  );

  function handleOrganizationChange(id: string) {
    setOrganizationOverride(id);
    setHierarchyId(null);
    setSelection(null);
    setFilterState(DEFAULT_FILTER_STATE);
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
    <div>
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
        />
      )}
      {/* F-1: below 1024px (Tailwind's `lg` breakpoint) the property panel kept its own minimum
          width and refused to shrink, squeezing the canvas down to an unusable ~167px column.
          Stacking the panel under the canvas on narrow screens, instead of forcing them to share
          one row, keeps the canvas at the full viewport width there. */}
      <div className="flex flex-col gap-4 lg:flex-row" data-testid="graph-layout">
        <div className="flex-1">
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
