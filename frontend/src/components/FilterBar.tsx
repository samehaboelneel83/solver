import { useEffect, useRef, useState } from "react";
import type { EntityTypeOption, GraphEdge } from "../types/graph";

export type FilterCriteria = {
  selectedTypes: string[] | null;
  search: string;
  highlightIds: string[] | null;
};

type FilterBarProps = {
  entityTypes: EntityTypeOption[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  onChange: (criteria: FilterCriteria) => void;
};

export default function FilterBar({ entityTypes, edges, selectedNodeId, onChange }: FilterBarProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set(entityTypes.map((et) => et.code)));
  const [search, setSearch] = useState("");
  const [highlighting, setHighlighting] = useState(false);

  function emit(types: Set<string>, searchValue: string, highlightingOn: boolean) {
    const allSelected = types.size === entityTypes.length;
    let highlightIds: string[] | null = null;
    if (highlightingOn && selectedNodeId) {
      const neighbors = new Set<string>([selectedNodeId]);
      for (const edge of edges) {
        if (edge.source === selectedNodeId) neighbors.add(edge.target);
        if (edge.target === selectedNodeId) neighbors.add(edge.source);
      }
      highlightIds = Array.from(neighbors);
    }
    onChange({ selectedTypes: allSelected ? null : Array.from(types), search: searchValue, highlightIds });
  }

  // Emit the current criteria on mount (so consumers start with an explicit default
  // rather than an implicit "no filter applied" state), and re-emit whenever the
  // selected node changes so `highlightIds` stays consistent with `selectedNodeId`:
  // cleared when the selection is lost, recomputed for the newly-selected node.
  const stateRef = useRef({ selected, search, highlighting });
  stateRef.current = { selected, search, highlighting };
  useEffect(() => {
    const { selected: currentSelected, search: currentSearch, highlighting: currentHighlighting } = stateRef.current;
    emit(currentSelected, currentSearch, currentHighlighting);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId]);

  function toggleType(code: string) {
    const next = new Set(selected);
    if (next.has(code)) {
      next.delete(code);
    } else {
      next.add(code);
    }
    setSelected(next);
    emit(next, search, highlighting);
  }

  function handleSearchChange(value: string) {
    setSearch(value);
    emit(selected, value, highlighting);
  }

  function toggleHighlight() {
    const next = !highlighting;
    setHighlighting(next);
    emit(selected, search, next);
  }

  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-2 text-sm">
      <input
        type="text"
        placeholder="Search by label or code…"
        value={search}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        data-testid="filter-search"
      />
      {entityTypes.map((et) => (
        <label key={et.id} className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={selected.has(et.code)}
            onChange={() => toggleType(et.code)}
            data-testid={`filter-type-${et.code}`}
          />
          {et.name}
        </label>
      ))}
      <button
        type="button"
        disabled={!selectedNodeId}
        onClick={toggleHighlight}
        className="rounded-md border border-slate-300 px-2 py-1 text-xs disabled:opacity-40"
        data-testid="filter-highlight-toggle"
      >
        {highlighting ? "Highlighting: On" : "Highlight connections"}
      </button>
    </div>
  );
}
