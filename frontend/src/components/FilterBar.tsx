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
  selectedNodeId: string | null;
  value: FilterState;
  onChange: (value: FilterState) => void;
  // H-1 fix round 1: fired with the search box's current text when Enter is pressed in it. This
  // is the audit's documented keyboard workaround ("type a node's label, press Enter") -- it
  // used to select nothing at all, because filtering (what this component already did) is not
  // the same as selecting. The caller (GraphDemo) owns the graph data and the selection, so it
  // resolves the match and opens the property panel; this component only reports the query.
  onSubmitSearch?: (query: string) => void;
  /** What the checkbox list groups by, for the button and the panel's
   * labels. "Types" in the objects view (a node's entity type); "Roles" in
   * the types view, where a node IS an entity type and its `type` is that
   * type's role. The matching itself is unchanged -- it is always
   * `node.type` against the given options' `name`. */
  typeNoun?: string;
  /** The search box's accessible name, which differs by view for the same
   * reason: it matches a node's label, which is an entity's label in one
   * view and a type's name in the other. */
  searchLabel?: string;
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

const SEARCH_DEBOUNCE_MS = 200;

const TYPES_PANEL_ID = "filter-types-panel";

export default function FilterBar({
  entityTypes,
  selectedNodeId,
  value,
  onChange,
  onSubmitSearch,
  typeNoun = "Types",
  searchLabel = "Search nodes by label",
}: FilterBarProps) {
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

  // H-1 fix round 1: Enter in the search box flushes any pending debounce immediately (so the
  // filter and the search-select below land in the same tick, instead of racing the trailing
  // ~200ms debounce timer) and reports the current text to the caller via onSubmitSearch.
  function handleSearchKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
      pendingSearchRef.current = null;
      onChangeRef.current({ ...valueRef.current, search: searchDraft });
    }
    onSubmitSearch?.(searchDraft);
  }

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
    // Keyed by NAME, because that is what a node's `type` is
    // (`entity_type.name`). `code` holds the same string, but only by way of
    // Task 7's mapping.
    () => (value.selectedTypes === null ? new Set(entityTypes.map((et) => et.name)) : new Set(value.selectedTypes)),
    [value.selectedTypes, entityTypes]
  );
  const totalCount = entityTypes.length;
  const selectedCount = selectedSet.size;

  function toggleType(name: string) {
    const next = new Set(selectedSet);
    if (next.has(name)) {
      next.delete(name);
    } else {
      next.add(name);
    }
    const allSelected = next.size === totalCount;
    onChange({ ...value, selectedTypes: allSelected ? null : Array.from(next) });
  }

  const visibleTypes = entityTypes
    .filter((et) => {
      const q = typeSearch.trim().toLowerCase();
      if (!q) return true;
      // `code` is the same string as `name` in v1 (both are
      // `entity_type.name`), so matching it too would be matching twice.
      return et.name.toLowerCase().includes(q);
    })
    // F-6: types were previously listed in insertion order, which forces a linear scan on a
    // large model -- alphabetical by name makes a specific type findable at a glance.
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-2 text-sm">
      <input
        type="text"
        placeholder="Search…"
        title={`${searchLabel} -- press Enter to select the first match`}
        aria-label={`${searchLabel} -- press Enter to select the first match`}
        value={searchDraft}
        onChange={(e) => handleSearchChange(e.target.value)}
        onKeyDown={handleSearchKeyDown}
        className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        data-testid="filter-search"
      />

      <div className="relative" onKeyDown={handlePanelKeyDown}>
        <button
          ref={typesToggleRef}
          type="button"
          onClick={() => setPanelOpen((v) => !v)}
          title={`Show or hide nodes by ${typeNoun.toLowerCase()}`}
          aria-haspopup="true"
          aria-expanded={panelOpen}
          aria-controls={TYPES_PANEL_ID}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs"
          data-testid="filter-types-toggle"
        >
          {typeNoun}: {selectedCount} of {totalCount}
        </button>
        {panelOpen && (
          <div
            id={TYPES_PANEL_ID}
            className="absolute z-10 mt-1 max-h-72 w-64 overflow-auto rounded-md border border-slate-300 bg-white p-2 shadow-md"
            data-testid="filter-types-panel"
          >
            <input
              type="text"
              placeholder={`Filter ${typeNoun.toLowerCase()}…`}
              title={`Filter the ${typeNoun.toLowerCase()} list`}
              aria-label={`Filter the ${typeNoun.toLowerCase()} list`}
              value={typeSearch}
              onChange={(e) => setTypeSearch(e.target.value)}
              className="mb-2 block w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
              data-testid="filter-type-search"
            />
            <div className="mb-2 flex gap-2">
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: null })}
                title={`Select all ${typeNoun.toLowerCase()}`}
                className="text-xs text-blue-600"
                data-testid="filter-types-all"
              >
                All
              </button>
              <button
                type="button"
                onClick={() => onChange({ ...value, selectedTypes: [] })}
                title={`Deselect all ${typeNoun.toLowerCase()}`}
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
                  checked={selectedSet.has(et.name)}
                  onChange={() => toggleType(et.name)}
                  data-testid={`filter-type-${et.name}`}
                />
                {/* The type's name, once: v1 has a single `name` column, and
                    the wire's `code` is that same string (Task 7's mapping),
                    so "{name} ({code})" rendered every type as "unit (unit)". */}
                {et.name}
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
