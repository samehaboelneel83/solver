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
 * silently discards text the user typed but didn't pick from the list.
 * Blurring with unmatched text either (a) selects the one option whose
 * label matches the typed text exactly, (b) if no selection existed yet,
 * keeps the typed text and says it didn't match, or (c) if a selection
 * already existed, reverts the display back to that selection's label and
 * names both in a message -- never (b) while `value` still points at an
 * unrelated row, which would let the screen and the saved record disagree
 * (fix round 1: this was the shape of the original C-1 bug, just moved one
 * step later). */
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
  // Set instead of `noMatch` when an unmatched blur happens while a prior
  // selection exists: holds the text that didn't match, purely for the
  // "kept your old selection" message. The display itself reverts to the
  // existing selection's label (see `inputValue`) so what's on screen can
  // never disagree with `value` -- see the fix-round-1 note below.
  const [revertedQuery, setRevertedQuery] = useState<string | null>(null);

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
      setRevertedQuery(null);
    }
  }, [value]);

  const displayLabel = selectedLabel ?? resolvedLabel ?? "";
  // While there's unmatched typed text AND no prior selection exists
  // (blurred without ever picking anything), keep showing it instead of
  // snapping back to empty -- that silent revert-to-empty is C-1. But once
  // a selection DOES exist, `query` is reset on an unmatched blur (below)
  // so this always falls through to `displayLabel` -- the screen can never
  // show text that doesn't match the stored `value`.
  const inputValue = isOpen ? query : noMatch ? query : displayLabel;
  const hasToken = Boolean(value) && !isOpen && !noMatch;

  function openFresh() {
    setIsOpen(true);
    setActiveIndex(-1);
    setRevertedQuery(null);
    if (!noMatch) {
      // Starting a fresh search rather than continuing to filter by the
      // previously selected label. An unmatched query (no prior selection)
      // is the opposite case -- keep it so the user can pick up editing
      // where they left off.
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
    setRevertedQuery(null);
  }

  function handleClear() {
    onChange("");
    setSelectedLabel(null);
    setQuery("");
    setIsOpen(false);
    setNoMatch(false);
    setRevertedQuery(null);
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
    setIsOpen(false);
    if (value) {
      // A selection already exists -- do NOT leave the typed text on
      // screen next to an unrelated stored id (that's the "displays Nurse,
      // saves Ward" regression). Revert the display to the existing
      // selection and say so; `value`/`onChange` are untouched either way.
      setRevertedQuery(query);
      setQuery("");
    } else {
      // C-1: nothing was ever selected, so there's nothing to disagree
      // with -- keep what was typed and say it didn't match.
      setNoMatch(true);
    }
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
      setRevertedQuery(null);
    }
  }

  const listId = testId ? `${testId}-listbox` : undefined;
  const noMatchId = testId ? `${testId}-no-match` : undefined;
  const revertedId = testId ? `${testId}-reverted` : undefined;
  const showNoMatchMessage = noMatch && !isOpen;
  const showRevertedMessage = revertedQuery !== null && !isOpen;
  const optionId = (index: number) => (listId ? `${listId}-option-${index}` : undefined);
  const activeDescendant = isOpen && activeIndex >= 0 ? optionId(activeIndex) : undefined;
  const combinedDescribedBy =
    [
      ariaDescribedBy,
      showNoMatchMessage ? noMatchId : undefined,
      showRevertedMessage ? revertedId : undefined,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

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
              setRevertedQuery(null);
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
      {showRevertedMessage && (
        <p id={revertedId} className="mt-1 text-xs text-amber-600" data-testid={revertedId}>
          {`No match for "${revertedQuery}" — keeping "${displayLabel}"`}
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
