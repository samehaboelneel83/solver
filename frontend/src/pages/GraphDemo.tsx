import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import GraphEditor from "../components/GraphEditor";
import PropertyPanel from "../components/PropertyPanel";
import FilterBar, { DEFAULT_FILTER_STATE, deriveFilterCriteria } from "../components/FilterBar";
import type { FilterState } from "../components/FilterBar";
import { useGraph } from "../api/graph";

type Selection = { kind: "node" | "edge"; id: string } | null;

function useDefaultOrganizationId() {
  return useQuery({
    queryKey: ["organizations", "default"],
    queryFn: async () => {
      const result = await apiFetch<{ items: { id: string; code: string }[]; total: number }>(
        "/api/iam/organization/?limit=50&offset=0"
      );
      const defaultOrg = result.items.find((item) => item.code === "default");
      return defaultOrg?.id ?? null;
    },
  });
}

export default function GraphDemo() {
  const { data: organizationId, isLoading: orgLoading } = useDefaultOrganizationId();
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  // Owned here (not inside FilterBar) so it survives GraphEditor's hierarchy-driven data
  // reload and FilterBar no longer needs a remount key to "reset" on hierarchy switch.
  const [filterState, setFilterState] = useState<FilterState>(DEFAULT_FILTER_STATE);

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

  if (orgLoading || !organizationId) {
    return <p className="text-sm text-slate-400">Loading organization…</p>;
  }

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Domain Graph</h1>
      {graph && (
        <FilterBar
          entityTypes={graph.entity_types}
          edges={graph.edges}
          selectedNodeId={selectedNodeId}
          value={filterState}
          onChange={setFilterState}
        />
      )}
      <div className="flex gap-4">
        <div className="flex-1">
          <GraphEditor
            organizationId={organizationId}
            hierarchyId={hierarchyId}
            onHierarchyChange={setHierarchyId}
            filter={filter}
            onSelectionChange={setSelection}
          />
        </div>
        <div className="w-72 shrink-0 rounded-md border border-slate-200 p-3">
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
