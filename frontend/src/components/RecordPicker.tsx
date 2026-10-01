import { KeyboardEvent, useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatApiError } from "../api/errors";
import { listEntities, useCreateEntity, type Entity, type Id } from "../api/v1";

const DEBOUNCE_MS = 200;
const PAGE = 20;

export type RecordPickerProps = {
  /** The kind of record to choose from; records of kinds inheriting from it are offered too. */
  typeId: Id | null;
  /** The chosen record's key, or "" for none. */
  value: string;
  onChange: (key: string) => void;
  id?: string;
  className?: string;
  required?: boolean;
  placeholder?: string;
  "data-testid"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  "aria-describedby"?: string;
  /** For a picker with no visible label (a grid cell). */
  "aria-label"?: string;
  /** Keys that may not be chosen here, each with the reason shown beside it (a cycle, the record itself). */
  blocked?: ReadonlyMap<string, string>;
  /** Offer to create a record with the typed key when none matches (the reader may edit records). */
  allowCreate?: boolean;
  /** The kind's name, for "Create … as a new <kind>". */
  kindName?: string;
};

function optionText(e: Pick<Entity, "key" | "label">): string {
  return e.label ? `${e.key} — ${e.label}` : e.key;
}

/**
 * Choose one record by typing: the server searches key and label (`?q=`), so a kind with
 * thousands of records is as easy to pick from as one with ten. Replaces a `<select>` that
 * loaded the first 500 and showed any later value as "not found".
 *
 * The chosen key is kept until another is picked or the field is cleared; text typed and
 * not picked never becomes the value. Keys in `blocked` are listed, greyed, with the reason.
 */
export default function RecordPicker({
  typeId,
  value,
  onChange,
  id,
  className,
  required,
  placeholder,
  "data-testid": testId,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
  "aria-label": ariaLabel,
  blocked,
  allowCreate,
  kindName,
}: RecordPickerProps) {
  const create = useCreateEntity();
  const [createError, setCreateError] = useState<string | null>(null);
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [text]);

  const results = useQuery({
    queryKey: ["record-picker", typeId, search],
    queryFn: () => listEntities({ entityTypeId: typeId, q: search || undefined, family: true, limit: PAGE }),
    enabled: open && typeId != null,
  });
  // The chosen record's label, wherever it sits in the list.
  const chosen = useQuery({
    queryKey: ["record-picker", typeId, "key", value],
    queryFn: () => listEntities({ entityTypeId: typeId, q: value, family: true, limit: PAGE }),
    enabled: typeId != null && value !== "",
    select: (page) => page.items.find((e) => e.key === value) ?? null,
  });

  const options = results.data?.items ?? [];
  const more = (results.data?.total ?? 0) > options.length;
  const missing = value !== "" && chosen.isSuccess && chosen.data === null;
  const shown = open ? text : value === "" ? "" : chosen.data ? optionText(chosen.data) : value;

  // The typed text, offered as a new record's key when nothing has exactly that key.
  const typed = text.trim();
  const canCreate =
    allowCreate && typeId != null && typed !== "" && search === typed && results.isSuccess && !options.some((e) => e.key === typed);

  async function createAndPick() {
    setCreateError(null);
    try {
      const made = await create.mutateAsync({ entity_type_id: typeId as Id, key: typed });
      pick(made.key);
    } catch (err) {
      setCreateError(formatApiError(err));
    }
  }

  function pick(key: string) {
    if (blocked?.has(key)) return;
    onChange(key);
    setOpen(false);
    setText("");
    setActive(-1);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && open && active >= 0 && options[active]) {
      event.preventDefault();
      pick(options[active].key);
    } else if (event.key === "Escape") {
      setOpen(false);
      setText("");
    }
  }

  return (
    <div className="relative">
      <div className="flex gap-1">
        <input
          id={id}
          data-testid={testId}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-invalid={ariaInvalid}
          aria-describedby={ariaDescribedBy}
          aria-label={ariaLabel}
          aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
          className={className}
          autoComplete="off"
          placeholder={placeholder ?? "Type to search…"}
          value={shown}
          onFocus={() => {
            setOpen(true);
            setText("");
          }}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onKeyDown={onKeyDown}
        />
        {!required && value !== "" && !open && (
          <button
            type="button"
            className="rounded-md border border-slate-300 px-2 text-xs text-slate-600 hover:bg-slate-50"
            aria-label="Clear"
            onClick={() => onChange("")}
          >
            ×
          </button>
        )}
      </div>
      {missing && <p className="mt-1 text-xs text-amber-700">“{value}” is not a record here any more.</p>}
      {createError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          Could not create it here: {createError}{" "}
          <Link to={`/entities/new?type=${typeId}`} className="underline">
            Open the full form
          </Link>
        </p>
      )}
      {open && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg"
        >
          {results.isLoading && <li className="px-3 py-1.5 text-slate-500">Searching…</li>}
          {results.isError && <li className="px-3 py-1.5 text-red-700">Could not search.</li>}
          {results.isSuccess && options.length === 0 && (
            <li className="px-3 py-1.5 text-slate-500">{search ? `Nothing matches “${search}”.` : "No records yet."}</li>
          )}
          {options.map((e, i) => {
            const why = blocked?.get(e.key);
            return (
              <li
                key={e.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={e.key === value}
                aria-disabled={why ? true : undefined}
                className={`px-3 py-1.5 ${why ? "cursor-not-allowed text-slate-400" : "cursor-pointer"} ${
                  i === active ? "bg-slate-100" : ""
                } ${e.key === value ? "font-medium" : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(e.key);
                }}
              >
                {optionText(e)}
                {why && <span className="ml-2 text-xs">({why})</span>}
              </li>
            );
          })}
          {more && <li className="px-3 py-1.5 text-xs text-slate-500">More records: type to narrow.</li>}
          {canCreate && (
            <li
              role="option"
              aria-selected={false}
              className="cursor-pointer border-t border-slate-100 px-3 py-1.5 text-blue-700"
              onMouseDown={(event) => {
                event.preventDefault();
                void createAndPick();
              }}
            >
              {create.isPending ? "Creating…" : `+ Create “${typed}” as a new ${kindName ?? "record"}`}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
