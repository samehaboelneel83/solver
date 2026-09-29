import { useEffect, useState } from "react";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

/**
 * The search for a long list (Epic UX, U-1): what the planner types is sent to the
 * server as `q` once they pause, so a list of thousands is searched, not only its
 * first page. A number also finds the item with that id.
 */
export default function SearchBox({
  label,
  onSearch,
  initial = "",
  delay = 250,
}: {
  /** What is being searched, e.g. "scenarios" -- read out as "Search scenarios". */
  label: string;
  onSearch: (q: string) => void;
  initial?: string;
  delay?: number;
}) {
  const [text, setText] = useState(initial);
  const settled = useDebouncedValue(text.trim(), delay);
  useEffect(() => onSearch(settled), [settled]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <label className="flex items-center gap-2 text-sm text-slate-700">
      <span className="sr-only">Search {label}</span>
      <input
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setText("");
        }}
        placeholder={`Search ${label} by name or id`}
        aria-label={`Search ${label}`}
        className="w-64 rounded-md border border-slate-300 px-2 py-1"
      />
    </label>
  );
}

/** "No scenarios match 'x'." -- an empty search result, never shown as an empty list. */
export function NoMatches({ label, q }: { label: string; q: string }) {
  return (
    <p role="status" className="my-2 text-sm text-slate-600">
      No {label} match &ldquo;{q}&rdquo;.
    </p>
  );
}
