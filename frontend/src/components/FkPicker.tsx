import { KeyboardEvent, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { optionLabelsQuery, useOptions } from "../api/options";
import { useSchema } from "../api/meta";
import { lowerFirst, tableLabelPlural } from "../lib/labels";
import type { TableMeta } from "../types/meta";

type FkPickerProps = {
  fkTable: string;
  value: string;
  onChange: (id: string) => void;
  required?: boolean;
  testId?: string;
  /** Forwarded to the underlying `<input>` so a caller (EntityForm) can
   * associate a real `<label htmlFor>` with it instead of wrapping (H-3/H-12). */
  id?: string;
  /** Forwarded to the underlying `<input>` so a caller can mark this field
   * invalid, e.g. a required-but-empty FK on a failed submit. */
  "aria-invalid"?: boolean | "true" | "false";
  /** Forwarded to the underlying `<input>` and merged with the picker's own
   * "no match" message id (if shown) so both reach assistive tech. */
  "aria-describedby"?: string;
};

const DEBOUNCE_MS = 250;

/** Searchable combobox for foreign-key fields: types a query against
 * `/options?q=`, picks a result to store its id, and shows a human label
 * instead of the raw id (resolved via `/options?ids=` when the current
 * value's label isn't already known from a search). Replaces the old
 * `<select>` that only ever showed the first 200 rows.
 *
 * C-1/C-2: the field now announces itself (placeholder + chevron), shows a
 * chosen value as a token rather than plain typed-looking text, and never
 * silently discards text the user typed but didn't pick from the list --
 * blurring with unmatched text keeps it and shows an explanatory message
 * (unless exactly one option matches the typed text exactly, which is
 * selected instead). */
export default function FkPicker({
  fkTable,
  value,
  onChange,
  required,
  testId,
  id,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
}: FkPickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [noMatch, setNoMatch] = useState(false);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const search = useOptions(fkTable, debouncedQuery, { enabled: isOpen || debouncedQuery.length > 0 });
  const options = query ? (search.data ?? []) : [];

  const labels = useQuery(optionLabelsQuery(fkTable, value ? [value] : []));
  const resolvedLabel = value ? labels.data?.[value] : undefined;

  // The target table's own label, e.g. "entity types" for fkTable
  // "domain.entity_type" -- lets the placeholder say what this field
  // searches ("Search entity types...") instead of nothing at all (C-2).
  const schema = useSchema();
  const tables: TableMeta[] = Array.isArray(schema.data) ? schema.data : [];
  const targetTable = tables.find((t) => `${t.schema}.${t.table}` === fkTable);
  const placeholder = targetTable ? `Search ${lowerFirst(tableLabelPlural(targetTable))}…` : "Search…";

  // Forget the locally-known label once the value is cleared (from here or
  // from outside, e.g. a form reset) so a later selection doesn't briefly
  // show a stale label.
  useEffect(() => {
    if (!value) {
      setSelectedLabel(null);
      setNoMatch(false);
    }
  }, [value]);

  const displayLabel = selectedLabel ?? resolvedLabel ?? "";
  // While there's unmatched typed text (blurred without a pick), keep
  // showing it instead of snapping back to the last selected label -- that
  // silent revert-to-empty is exactly C-1.
  const inputValue = isOpen ? query : noMatch ? query : displayLabel;
  const hasToken = Boolean(value) && !isOpen && !noMatch;

  function openFresh() {
    setIsOpen(true);
    setActiveIndex(-1);
    if (!noMatch) {
      // Starting a fresh search rather than continuing to filter by the
      // previously selected label. An unmatched query is the opposite case
      // -- keep it so the user can pick up editing where they left off.
      setQuery("");
      setDebouncedQuery("");
    }
  }

  function selectOption(option: { id: string; label: string }) {
    setSelectedLabel(option.label);
    onChange(option.id);
    setIsOpen(false);
    setQuery("");
    setActiveIndex(-1);
    setNoMatch(false);
  }

  function handleClear() {
    onChange("");
    setSelectedLabel(null);
    setQuery("");
    setIsOpen(false);
    setNoMatch(false);
  }

  function handleBlur() {
    if (query === "") {
      setIsOpen(false);
      return;
    }
    const exactMatches = options.filter((option) => option.label === query);
    if (exactMatches.length === 1) {
      selectOption(exactMatches[0]);
      return;
    }
    // C-1: don't silently empty the field. Leave `value`/`onChange` alone,
    // keep what was typed, and say so.
    setIsOpen(false);
    setNoMatch(true);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!isOpen) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (activeIndex >= 0 && options[activeIndex]) {
        selectOption(options[activeIndex]);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      setQuery("");
      setNoMatch(false);
    }
  }

  const listId = testId ? `${testId}-listbox` : undefined;
  const noMatchId = testId ? `${testId}-no-match` : undefined;
  const showNoMatchMessage = noMatch && !isOpen;
  const optionId = (index: number) => (listId ? `${listId}-option-${index}` : undefined);
  const activeDescendant = isOpen && activeIndex >= 0 ? optionId(activeIndex) : undefined;
  const combinedDescribedBy =
    [ariaDescribedBy, showNoMatchMessage ? noMatchId : undefined].filter(Boolean).join(" ") || undefined;

  return (
    <div className="relative">
      <div className="mt-1 flex items-center gap-1">
        <div className="relative flex-1">
          <input
            id={id}
            type="text"
            role="combobox"
            aria-expanded={isOpen}
            aria-controls={isOpen ? listId : undefined}
            aria-activedescendant={activeDescendant}
            aria-invalid={ariaInvalid}
            aria-describedby={combinedDescribedBy}
            autoComplete="off"
            required={required && !value}
            placeholder={placeholder}
            className={`w-full rounded-md border px-3 py-2 pr-8 text-sm ${
              hasToken ? "border-slate-300 bg-slate-100 font-medium text-slate-900" : "border-slate-300"
            }`}
            value={inputValue}
            onFocus={openFresh}
            onChange={(e) => {
              setQuery(e.target.value);
              setIsOpen(true);
              setActiveIndex(-1);
              setNoMatch(false);
            }}
            onKeyDown={handleKeyDown}
            onBlur={handleBlur}
            data-testid={testId}
          />
          <span
            aria-hidden="true"
            data-testid={testId ? `${testId}-chevron` : undefined}
            className={`pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-400 transition-transform ${
              isOpen ? "rotate-180" : ""
            }`}
          >
            ▾
          </span>
        </div>
        {value && (
          <button
            type="button"
            aria-label="Clear selection"
            className="rounded-md border border-slate-300 px-2 py-2 text-xs text-slate-500 hover:bg-slate-100"
            onMouseDown={(e) => e.preventDefault()}
            onClick={handleClear}
          >
            ×
          </button>
        )}
      </div>
      {showNoMatchMessage && (
        <p id={noMatchId} className="mt-1 text-xs text-red-600" data-testid={noMatchId}>
          No match — choose from the list
        </p>
      )}
      {isOpen && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border border-slate-300 bg-white text-sm shadow-md"
        >
          {query === "" ? (
            <li className="px-3 py-2 text-slate-500">Type to search</li>
          ) : search.isLoading ? (
            <li className="px-3 py-2 text-slate-500">Searching…</li>
          ) : options.length === 0 ? (
            <li className="px-3 py-2 text-slate-500">No matches</li>
          ) : (
            options.map((option, index) => (
              <li
                key={option.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === activeIndex}
                className={`cursor-pointer px-3 py-2 ${index === activeIndex ? "bg-slate-100" : ""}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectOption(option);
                }}
              >
                {option.label}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
