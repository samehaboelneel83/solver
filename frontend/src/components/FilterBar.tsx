import { useMemo, useState } from "react";
import type { EntityTypeOption, GraphEdge } from "../types/graph";

export type FilterCriteria = {
  selectedTypes: string[] | null;
  search: string;
  highlightIds: string[] | null;
};

/** The bit of filter state GraphDemo owns and persists across GraphEditor
 * remounts/hierarchy switches. `selectedTypes: null` means "all types" (the
 * default) rather than listing every type code. */
export type FilterState = {
  selectedTypes: string[] | null;
  search: string;
  highlighting: boolean;
};

export const DEFAULT_FILTER_STATE: FilterState = { selectedTypes: null, search: "", highlighting: false };

type FilterBarProps = {
  entityTypes: EntityTypeOption[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  value: FilterState;
  onChange: (value: FilterState) => void;
};

/**
 * Pure derivation of the `FilterCriteria` GraphEditor actually filters/highlights by, from
 * the controlled `FilterState` plus the current selection and the graph's edges. Exported
 * (rather than folded into the component) so GraphDemo can compute `filter` for GraphEditor
 * without rendering FilterBar, and so the highlight-neighbor computation is unit-testable
 * on its own.
 */
export function deriveFilterCriteria(
  state: FilterState,
  selectedNodeId: string | null,
  edges: GraphEdge[]
): FilterCriteria {
  let highlightIds: string[] | null = null;
  if (state.highlighting && selectedNodeId) {
    const neighbors = new Set<string>([selectedNodeId]);
    for (const edge of edges) {
      if (edge.source === selectedNodeId) neighbors.add(edge.target);
      if (edge.target === selectedNodeId) neighbors.add(edge.source);
    }
    highlightIds = Array.from(neighbors);
  }
  return { selectedTypes: state.selectedTypes, search: state.search, highlightIds };
}

export default function FilterBar({ entityTypes, edges: _edges, selectedNodeId, value, onChange }: FilterBarProps) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [typeSearch, setTypeSearch] = useState("");

  const selectedSet = useMemo(
    () => (value.selectedTypes === null ? new Set(entityTypes.map((et) => et.code)) : new Set(value.selectedTypes)),
    [value.selectedTypes, entityTypes]
  );
  const totalCount = entityTypes.length;
  const selectedCount = selectedSet.size;

  function toggleType(code: string) {
    const next = new Set(selectedSet);
    if (next.has(code)) {
      next.delete(code);
    } else {
      next.add(code);
    }
    const allSelected = next.size === totalCount;
    onChange({ ...value, selectedTypes: allSelected ? null : Array.from(next) });
  }

  const visibleTypes = entityTypes.filter((et) => {
    const q = typeSearch.trim().toLowerCase();
    if (!q) return true;
    return et.name.toLowerCase().includes(q) || et.code.toLowerCase().includes(q);
  });

  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-2 text-sm">
      <input
        type="text"
        placeholder="Search by label or code…"
        value={value.search}
        onChange={(e) => onChange({ ...value, search: e.target.value })}
        className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        data-testid="filter-search"
      />

      <div className="relative">
        <button
          type="button"
          onClick={() => setPanelOpen((v) => !v)}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs"
          data-testid="filter-types-toggle"
        >
          Types: {selectedCount} of {totalCount}
        </button>
        {panelOpen && (
          <div
            className="absolute z-10 mt-1 max-h-72 w-64 overflow-auto rounded-md border border-slate-300 bg-white p-2 shadow-md"
            data-testid="filter-types-panel"
          >
            <input
              type="text"
              placeholder="Filter types…"
              value={typeSearch}
              onChange={(e) => setTypeSearch(e.target.value)}
              className="mb-2 block w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
              data-testid="filter-type-search"
            />
            <div className="mb-2 flex gap-2">
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: null })}
                className="text-xs text-blue-600"
                data-testid="filter-types-all"
              >
                All
              </button>
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: [] })}
                className="text-xs text-blue-600"
                data-testid="filter-types-none"
              >
                None
              </button>
            </div>
            {visibleTypes.map((et) => (
              <label key={et.id} className="flex items-center gap-1 py-0.5 text-xs">
                <input
                  type="checkbox"
                  checked={selectedSet.has(et.code)}
                  onChange={() => toggleType(et.code)}
                  data-testid={`filter-type-${et.code}`}
                />
                {et.name} ({et.code})
              </label>
            ))}
          </div>
        )}
      </div>

      <button
        type="button"
        disabled={!selectedNodeId}
        onClick={() => onChange({ ...value, highlighting: !value.highlighting })}
        className="rounded-md border border-slate-300 px-2 py-1 text-xs disabled:opacity-40"
        data-testid="filter-highlight-toggle"
      >
        {value.highlighting ? "Highlighting: On" : "Highlight connections"}
      </button>
    </div>
  );
}
