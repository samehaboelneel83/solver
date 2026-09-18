import { useEffect, useMemo, useRef, useState, KeyboardEvent as ReactKeyboardEvent } from "react";
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

// `edges` is part of FilterBar's props contract (task-9-brief.md) and is what GraphDemo passes
// through to `deriveFilterCriteria` for the highlight computation -- but that derivation now
// happens in GraphDemo itself (not inside this component), so `edges` isn't read here. Kept on
// the signature rather than dropped so the prop list matches the documented contract and stays
// available to any future in-component use (e.g. showing edge counts in the type panel).
const SEARCH_DEBOUNCE_MS = 200;

const TYPES_PANEL_ID = "filter-types-panel";

export default function FilterBar({ entityTypes, edges: _edges, selectedNodeId, value, onChange }: FilterBarProps) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [typeSearch, setTypeSearch] = useState("");
  const typesToggleRef = useRef<HTMLButtonElement | null>(null);

  function closeTypesPanel() {
    setPanelOpen(false);
    typesToggleRef.current?.focus();
  }

  function handlePanelKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      closeTypesPanel();
    }
  }

  // The search box's own text is local state so typing stays instant and
  // responsive; the (expensive, re-styles every node/edge) onChange call up
  // to GraphDemo is debounced ~200ms behind it. Kept in refs rather than
  // captured in the closure below so a debounced call that fires after
  // `value`/`onChange` changed (e.g. selectedTypes toggled while the user
  // was still typing) still merges onto the *current* value, not a stale one.
  const [searchDraft, setSearchDraft] = useState(value.search);
  const valueRef = useRef(value);
  valueRef.current = value;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The most recent typed value not yet committed via onChange, or null once
  // it has been (or there's nothing pending). Lets unmount flush it instead
  // of silently dropping it -- see the cleanup effect below.
  const pendingSearchRef = useRef<string | null>(null);

  // Resync the local draft when `search` changes from outside (e.g.
  // GraphDemo resetting filterState on an organisation switch), but not as
  // a reaction to our own debounced onChange below -- by the time that
  // fires, value.search already equals searchDraft, so this is a no-op then.
  useEffect(() => {
    setSearchDraft(value.search);
  }, [value.search]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        // Flush rather than drop a still-pending debounced search on unmount
        // -- GraphDemo remounts this component whenever its `graph` query
        // goes transiently undefined (e.g. mid-refetch on a hierarchy
        // switch), and a keystroke typed just before that would otherwise
        // vanish even though the input still visibly showed it.
        if (pendingSearchRef.current !== null) {
          onChangeRef.current({ ...valueRef.current, search: pendingSearchRef.current });
        }
      }
    };
  }, []);

  function handleSearchChange(next: string) {
    setSearchDraft(next);
    pendingSearchRef.current = next;
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      pendingSearchRef.current = null;
      onChangeRef.current({ ...valueRef.current, search: next });
    }, SEARCH_DEBOUNCE_MS);
  }

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

  const visibleTypes = entityTypes
    .filter((et) => {
      const q = typeSearch.trim().toLowerCase();
      if (!q) return true;
      return et.name.toLowerCase().includes(q) || et.code.toLowerCase().includes(q);
    })
    // F-6: types were previously listed in insertion order, which forces a linear scan on a
    // large model -- alphabetical by name makes a specific type findable at a glance.
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-2 text-sm">
      <input
        type="text"
        placeholder="Search by label or code…"
        title="Search nodes by label or code"
        aria-label="Search nodes by label or code"
        value={searchDraft}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        data-testid="filter-search"
      />

      <div className="relative" onKeyDown={handlePanelKeyDown}>
        <button
          ref={typesToggleRef}
          type="button"
          onClick={() => setPanelOpen((v) => !v)}
          title="Show or hide node types"
          aria-haspopup="true"
          aria-expanded={panelOpen}
          aria-controls={TYPES_PANEL_ID}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs"
          data-testid="filter-types-toggle"
        >
          Types: {selectedCount} of {totalCount}
        </button>
        {panelOpen && (
          <div
            id={TYPES_PANEL_ID}
            className="absolute z-10 mt-1 max-h-72 w-64 overflow-auto rounded-md border border-slate-300 bg-white p-2 shadow-md"
            data-testid="filter-types-panel"
          >
            <input
              type="text"
              placeholder="Filter types…"
              title="Filter the type list"
              aria-label="Filter the type list"
              value={typeSearch}
              onChange={(e) => setTypeSearch(e.target.value)}
              className="mb-2 block w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
              data-testid="filter-type-search"
            />
            <div className="mb-2 flex gap-2">
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: null })}
                title="Select all types"
                className="text-xs text-blue-600"
                data-testid="filter-types-all"
              >
                All
              </button>
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: [] })}
                title="Deselect all types"
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
        title={
          selectedNodeId
            ? "Highlight the selected node's direct connections and dim the rest"
            : "Select a node first to highlight its connections"
        }
        className="rounded-md border border-slate-300 px-2 py-1 text-xs disabled:opacity-40"
        data-testid="filter-highlight-toggle"
      >
        {value.highlighting ? "Highlighting: On" : "Highlight connections"}
      </button>
    </div>
  );
}
