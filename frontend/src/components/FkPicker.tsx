import { KeyboardEvent, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { optionLabelsQuery, useOptions } from "../api/options";

type FkPickerProps = {
  fkTable: string;
  value: string;
  onChange: (id: string) => void;
  required?: boolean;
  testId?: string;
};

const DEBOUNCE_MS = 250;

/** Searchable combobox for foreign-key fields: types a query against
 * `/options?q=`, picks a result to store its id, and shows a human label
 * instead of the raw id (resolved via `/options?ids=` when the current
 * value's label isn't already known from a search). Replaces the old
 * `<select>` that only ever showed the first 200 rows. */
export default function FkPicker({ fkTable, value, onChange, required, testId }: FkPickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const search = useOptions(fkTable, debouncedQuery, { enabled: isOpen || debouncedQuery.length > 0 });
  const options = query ? (search.data ?? []) : [];

  const labels = useQuery(optionLabelsQuery(fkTable, value ? [value] : []));
  const resolvedLabel = value ? labels.data?.[value] : undefined;

  // Forget the locally-known label once the value is cleared (from here or
  // from outside, e.g. a form reset) so a later selection doesn't briefly
  // show a stale label.
  useEffect(() => {
    if (!value) {
      setSelectedLabel(null);
    }
  }, [value]);

  const displayLabel = selectedLabel ?? resolvedLabel ?? "";
  const inputValue = isOpen ? query : displayLabel;

  function openFresh() {
    setIsOpen(true);
    setQuery("");
    setDebouncedQuery("");
    setActiveIndex(-1);
  }

  function selectOption(option: { id: string; label: string }) {
    setSelectedLabel(option.label);
    onChange(option.id);
    setIsOpen(false);
    setQuery("");
    setActiveIndex(-1);
  }

  function handleClear() {
    onChange("");
    setSelectedLabel(null);
    setQuery("");
    setIsOpen(false);
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
    }
  }

  const listId = testId ? `${testId}-listbox` : undefined;

  return (
    <div className="relative">
      <div className="mt-1 flex items-center gap-1">
        <input
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listId}
          autoComplete="off"
          required={required && !value}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={inputValue}
          onFocus={openFresh}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
            setActiveIndex(-1);
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            setIsOpen(false);
            setQuery("");
          }}
          data-testid={testId}
        />
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
      {isOpen && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border border-slate-300 bg-white text-sm shadow-md"
        >
          {query === "" ? (
            <li className="px-3 py-2 text-slate-400">Type to search</li>
          ) : search.isLoading ? (
            <li className="px-3 py-2 text-slate-400">Searching…</li>
          ) : options.length === 0 ? (
            <li className="px-3 py-2 text-slate-400">No matches</li>
          ) : (
            options.map((option, index) => (
              <li
                key={option.id}
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
