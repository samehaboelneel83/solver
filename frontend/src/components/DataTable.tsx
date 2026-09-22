import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { optionLabelsQuery } from "../api/options";
import { useShowIdentifiers } from "../hooks/useShowIdentifiers";
import { fieldLabel, lowerFirst, recordLabel } from "../lib/labels";
import { formatCellValue } from "../lib/format";
import type { FieldMeta } from "../types/meta";

type Row = Record<string, unknown>;

type DataTableProps = {
  /** Schema/table names (raw, not the human label) used to build each row's link. */
  schema: string;
  table: string;
  /** Human, plural table name, e.g. "Entity types" -- used for the caption
   * and the empty state ("No entity types yet"). */
  tableLabel: string;
  /** Link target for "create a new record", reused by the empty state.
   * Omit when the viewer cannot create records. */
  newHref?: string;
  fields: FieldMeta[];
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  orderBy?: string;
  order?: "asc" | "desc";
  onSort?: (column: string) => void;
  onPageChange: (offset: number) => void;
  onDelete?: (id: string, label: string) => void;
  onRowClick?: (id: string) => void;
};

/**
 * A column that can only ever show a bare, unreadable identifier: the
 * primary key `id` (a `uuid` on the `iam` tables, a `bigint` -- reported as
 * `integer` -- on every schema v1 table), or a `uuid`-typed column with
 * nowhere to resolve a label from. Hidden by default (behind "Show
 * identifiers") so a raw key doesn't push meaningful columns out of view
 * (E-4).
 *
 * A foreign-key column is never an identifier column, even though its name
 * typically ends in `_id` and, under v1, it is an `integer` just like the
 * surrogate key: it resolves to a human label ("Rostering", "Default
 * Organization"), which is real information a planner scans the list for.
 * That holds for a key *named* `id` too, when it is itself a foreign key (a
 * shared primary key). Keying on `is_fk` rather than on the column's type
 * is what keeps this right under identity keys, where the type no longer
 * tells a surrogate key from a reference. If a given row's label lookup
 * fails, that one cell falls back to showing its raw id -- the column
 * itself stays visible rather than being hidden for the whole table over
 * one failed lookup.
 */
export function isIdentifierColumn(field: FieldMeta): boolean {
  if (field.is_fk) return false;
  return field.name === "id" || field.type === "uuid";
}

/** A cell with nothing to show (the same test `formatCellValue` uses). */
function isEmptyValue(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/**
 * A plain click on the row's own link already navigates once, via the
 * `<a>` itself; the `<tr>`'s onClick exists only as a convenience for
 * clicks elsewhere in the row (E-1). Without this guard, clicking the link
 * fired *both* navigations -- pushing two history entries for one click, and
 * (worse) a ctrl/cmd/shift-click meant to open the record in a new tab also
 * navigated the current tab, because the row handler doesn't understand
 * "open in a new tab" clicks the way the link's own click handler does.
 */
function shouldIgnoreRowClick(event: React.MouseEvent<HTMLElement>): boolean {
  if (event.defaultPrevented) return true;
  if (event.button !== 0) return true;
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return true;
  return Boolean((event.target as HTMLElement).closest("a"));
}

/**
 * Whether a row's `id` is usable for building a real `<a href>`/navigation
 * target. On master this was only ever read inside an `onClick`, so a
 * missing id silently degraded to a no-op click; it's now built into a real
 * `<a href="…">` rendered twice per row (here and in the small-screen card),
 * so an unguarded `String(row.id)` would instead render a live link to
 * "…/undefined". Defensive ahead of the next project's move to composite
 * primary keys, where a single `id` column may not exist at all.
 */
/**
 * Most factory tables use `id`. `iam.capability` is keyed by `code`
 * (`domain.edit`); without this a row would render with no link.
 */
function rowIdentity(row: Row): string | undefined {
  if (row.id !== null && row.id !== undefined && row.id !== "") return String(row.id);
  if (typeof row.code === "string" && row.code !== "") return row.code;
  return undefined;
}

/**
 * The link to a row's own record, rendered on its first visible cell. That
 * cell can legitimately be empty -- `iam.organization`'s first column is a
 * nullable `parent_id` -- and an `<a>` with no text has no accessible name
 * (axe `link-name`, serious) and nothing visible to click. In that case it
 * shows a dash and takes its name from the record's own label instead.
 */
function RowLink({
  to,
  title,
  empty,
  recordLabel,
  children,
}: {
  to: string;
  title?: string;
  empty: boolean;
  recordLabel: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      title={title}
      aria-label={empty ? `Open ${recordLabel}` : undefined}
      className="font-medium text-blue-700 hover:underline"
    >
      {empty ? <span aria-hidden="true">—</span> : children}
    </Link>
  );
}

function idsForColumns(rows: Row[], columns: string[]): string[] {
  const values = new Set<string>();
  for (const row of rows) {
    for (const col of columns) {
      const value = row[col];
      if (value !== null && value !== undefined && value !== "") {
        values.add(String(value));
      }
    }
  }
  return Array.from(values);
}

// G-3 fix round 2: a single "Delete" item is ~44px tall (the menu's own
// `py-1` plus one item's `py-1.5` + text) -- used as a fallback estimate
// for the very first layout pass, before the menu has actually rendered
// into the portal and can report its own real height (see the comment on
// RowActionsMenu below for why a two-pass measurement isn't worth the
// complexity here).
const MENU_HEIGHT_ESTIMATE = 44;

/**
 * The row's delete affordance (G-3), factored out so it can be rendered once
 * in the table row and once in the small-screen card (fix round 1 for G-4) --
 * below 768px the table is `hidden`, and before this the card had no
 * actions trigger at all, leaving no way to delete a record on a narrow
 * screen. Each rendered instance owns its own open/closed state and DOM
 * refs (rather than a single table-wide "which row is open" ref) precisely
 * because two instances -- one in the table, one in the card -- exist in
 * the DOM at once for the same row; sharing one ref across both would have
 * the outside-click listener watching whichever instance last claimed the
 * ref, not necessarily the one the user actually opened.
 */
function RowActionsMenu({ row, label, onDelete }: { row: Row; label: string; onDelete: (row: Row) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [placement, setPlacement] = useState<{ top: number; right: number } | null>(null);

  // G-3 fix round 2: this menu used to be `absolute` inside the table's own
  // `overflow-x-auto` wrapper. CSS requires a non-`visible` `overflow-x` to
  // make `overflow-y` compute to `auto` too (per spec) even though the
  // wrapper only ever wanted horizontal scrolling, so that wrapper clipped
  // the dropdown vertically for any row near the bottom of the scrollable
  // area -- Delete was physically unreachable there (confirmed with
  // `elementFromPoint`, not a Playwright click, since Playwright
  // auto-scrolls a target into view before clicking and would hide this).
  // Rendering the dropdown into a portal at `position: fixed`, positioned
  // from the trigger's own bounding rect, escapes every ancestor's overflow
  // clipping -- including `<main>`'s `contain: layout`, which *is* a
  // containing block for `position: fixed` descendants, but only for ones
  // still inside it; portaling straight to `document.body` sidesteps that
  // entirely. Flips upward when there isn't room below.
  useLayoutEffect(() => {
    if (!isOpen) {
      setPlacement(null);
      return;
    }
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUpward = spaceBelow < MENU_HEIGHT_ESTIMATE + 8;
    setPlacement({
      top: openUpward ? rect.top - MENU_HEIGHT_ESTIMATE - 4 : rect.bottom + 4,
      right: window.innerWidth - rect.right,
    });
  }, [isOpen]);

  // Close this menu on an outside click. The trigger is excluded explicitly
  // now -- it's no longer a DOM ancestor of the (portaled) menu, so without
  // this a click on the trigger to close an open menu would also be seen as
  // an "outside" click and race with the trigger's own toggle handler.
  useEffect(() => {
    if (!isOpen) return;
    function handleClick(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setIsOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [isOpen]);

  // Escape closes the menu and returns focus to the trigger. A document
  // listener (rather than onKeyDown on a wrapper) since the portaled menu
  // is no longer a shared DOM subtree with the trigger to attach one to.
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  // The menu is `position: fixed`, positioned once from the trigger's rect in
  // the layout effect above, so anything that moves the trigger afterwards
  // leaves it stranded at stale viewport coordinates.
  //
  // T11 fix: this previously listened only on the table's own
  // `.overflow-x-auto` wrapper, which missed the two cases that actually
  // happen. `<main>` is the app's scroll container, so scrolling the page
  // slid the row out from under the menu -- measured at 150px of drift
  // (trigger moved 217 -> 67 while the menu stayed pinned at 253), leaving
  // a Delete floating over an unrelated row. A window resize stranded it
  // too (124px horizontal offset), since the stored `right` is an offset
  // from the old viewport width.
  //
  // `scroll` doesn't bubble, so the listener is registered in the capture
  // phase on `window` to catch it from *any* scrolling ancestor -- `<main>`,
  // the table wrapper, or any future one -- rather than naming a class.
  useEffect(() => {
    if (!isOpen) return;
    function dismiss() {
      setIsOpen(false);
    }
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    return () => {
      window.removeEventListener("scroll", dismiss, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        data-testid="row-actions"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={`Actions for ${label}`}
        ref={triggerRef}
        onClick={(event) => {
          event.stopPropagation();
          setIsOpen((open) => !open);
        }}
        className="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-900"
      >
        <span aria-hidden="true">⋮</span>
      </button>
      {isOpen &&
        placement &&
        createPortal(
          // axe's "region" best-practice rule flags any visible node with real
          // content whose own role isn't a landmark/aria-live role (or button/
          // iframe/skip-link) -- role="menu" on the menu itself does not exempt
          // it, so this portal (a direct child of <body>, outside every
          // landmark) was the violation's own target, not some ancestor
          // missing a landmark. Swapping role="menu" for a landmark role here
          // isn't an option either: role="menuitem" below requires an
          // ancestor with role="menu"/"menubar"/"group", so removing it would
          // trade this moderate/best-practice finding for a WCAG-A
          // aria-required-parent one. A role="region" wrapper around the
          // existing, unchanged menu is itself exempt and stops axe's
          // traversal before it reaches the menu -- the real menu/menuitem
          // semantics stay exactly as they were.
          <div
            role="region"
            aria-label="Row actions"
            style={{ position: "fixed", top: placement.top, right: placement.right }}
            // G-6: was z-10, the lowest of the app's four fixed layers (toast
            // z-50, drawer z-40, backdrop z-30) -- a toast is pointer-events-
            // auto, so overlap was geometrically possible at short viewports
            // even though it couldn't be reproduced. z-[60] puts the menu
            // above all of them.
            className="z-[60]"
          >
            <div
              ref={menuRef}
              role="menu"
              className="min-w-[8rem] rounded-md border border-slate-200 bg-white py-1 shadow-md"
            >
              <button
                type="button"
                role="menuitem"
                onClick={(event) => {
                  event.stopPropagation();
                  setIsOpen(false);
                  onDelete(row);
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-red-600 hover:bg-red-50"
              >
                Delete
              </button>
            </div>
          </div>,
          document.body
        )}
    </>
  );
}

export default function DataTable({
  schema,
  table,
  tableLabel,
  newHref,
  fields,
  rows,
  total,
  limit,
  offset,
  orderBy,
  order,
  onSort,
  onPageChange,
  onDelete,
  onRowClick,
}: DataTableProps) {
  // B-1/E-4: shared with EntityList's and EntityDetail's schema.table subtitle -- one "?ids=1"
  // flag gates every raw-identifier surface on a page, not just this table's own id column.
  const [showIds, toggleShowIds] = useShowIdentifiers();

  const displayFields = fields.filter((f) => !f.write_only && (showIds || !isIdentifierColumn(f)));

  // FK columns, grouped by the table they reference: one label query per
  // distinct FK table on the page. useQueries (rather than calling
  // useOptionLabels in a loop) is safe even if the number of FK tables
  // changes between renders of the same DataTable instance. Computed from
  // every field (not just the currently-displayed ones) so toggling
  // identifiers on doesn't have to wait out a fresh fetch.
  const fkFields = fields.filter((f) => f.is_fk && f.fk_table) as (FieldMeta & { fk_table: string })[];
  const fkTables = Array.from(new Set(fkFields.map((f) => f.fk_table)));
  const labelResults = useQueries({
    queries: fkTables.map((fkTable) => {
      const columnsForTable = fkFields.filter((f) => f.fk_table === fkTable).map((f) => f.name);
      const ids = idsForColumns(rows, columnsForTable);
      return optionLabelsQuery(fkTable, ids);
    }),
  });

  function labelFor(col: string, id: string): string {
    const fkTable = fkFields.find((f) => f.name === col)?.fk_table;
    if (!fkTable) return id;
    const index = fkTables.indexOf(fkTable);
    const labels = index >= 0 ? labelResults[index]?.data : undefined;
    return labels?.[id] ?? id;
  }

  function handleDeleteClick(row: Row) {
    if (!onDelete) return;
    const label = recordLabel({ fields }, row) ?? "this row";
    if (window.confirm(`Delete "${label}"? This cannot be undone.`)) {
      onDelete(rowIdentity(row) ?? "", label);
    }
  }

  /**
   * One cell's rendered content and title, shared between the table markup
   * and the small-screen card markup below (G-4) so the two never resolve a
   * foreign key or format a value differently.
   */
  function cellContent(field: FieldMeta, row: Row): { content: React.ReactNode; title?: string } {
    const value = row[field.name];
    const isFk = fkFields.some((f) => f.name === field.name);
    if (isFk && value !== null && value !== undefined && value !== "") {
      const id = String(value);
      return { content: labelFor(field.name, id), title: id };
    }
    const formatted = formatCellValue(field, value);
    const content = formatted.ariaLabel ? (
      <span aria-label={formatted.ariaLabel}>{formatted.text}</span>
    ) : (
      formatted.text
    );
    return { content, title: formatted.title };
  }

  if (total === 0) {
    return (
      <div>
        <div className="rounded-md border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
          <p>{`No ${lowerFirst(tableLabel)} yet`}</p>
          {newHref && (
          <Link to={newHref} className="mt-2 inline-block rounded py-1 text-sm font-medium text-blue-700 hover:underline">
            New
          </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex justify-end">
        {/* H-9: was text-only with no padding (84x16px, under the 24x24 Target Size minimum) --
            py-2 brings it to 32px tall. */}
        <button
          type="button"
          onClick={toggleShowIds}
          aria-pressed={showIds}
          className="rounded px-2 py-2 text-xs text-slate-500 underline hover:text-slate-700"
        >
          {showIds ? "Hide identifiers" : "Show identifiers"}
        </button>
      </div>
      {/* G-4: below `md` the table used to force horizontal scrolling to read
          a row -- at a 200% zoom equivalent (640x400) it overflowed by
          812px. Below `md` each row now renders as a labelled-pair card
          instead (CSS-only switch, no JS viewport listener); at `md` and up
          the table below takes over. Both markups are always in the DOM --
          only one is visible at a time via the `md:` classes. */}
      <div className="grid grid-cols-1 gap-3 md:hidden" data-testid="datatable-cards">
        {rows.map((row, index) => {
          const rowId = rowIdentity(row);
          const rowHref = rowId !== undefined ? `/${schema}/${table}/${rowId}` : undefined;
          const label = recordLabel({ fields }, row) ?? "this row";
          const firstField = displayFields[0];
          const restFields = displayFields.slice(1);
          const first = firstField ? cellContent(firstField, row) : null;
          return (
            <div
              key={rowId ?? `row-${index}`}
              data-testid="datatable-card"
              onClick={(event) => {
                if (shouldIgnoreRowClick(event)) return;
                if (rowId !== undefined) onRowClick?.(rowId);
              }}
              className={`rounded-md border border-slate-200 bg-white p-3 ${onRowClick ? "cursor-pointer" : ""}`}
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                {firstField &&
                  (rowHref !== undefined ? (
                    <RowLink
                      to={rowHref}
                      title={first?.title}
                      empty={isEmptyValue(row[firstField.name])}
                      recordLabel={label}
                    >
                      {first?.content}
                    </RowLink>
                  ) : (
                    <span title={first?.title} className="font-medium text-slate-900">
                      {first?.content}
                    </span>
                  ))}
                {/* G-4 fix round 1: below 768px the table (and its only
                    actions trigger) is hidden -- without this, there was no
                    way to delete a record on a narrow screen at all. */}
                {onDelete && <RowActionsMenu row={row} label={label} onDelete={handleDeleteClick} />}
              </div>
              {restFields.length > 0 && (
                <dl className="space-y-1 text-sm">
                  {restFields.map((field) => {
                    const { content, title } = cellContent(field, row);
                    return (
                      <div key={field.name} title={title} className="flex items-baseline justify-between gap-3">
                        <dt className="text-slate-500">{fieldLabel(field)}</dt>
                        <dd className="text-right text-slate-900">{content}</dd>
                      </div>
                    );
                  })}
                </dl>
              )}
            </div>
          );
        })}
      </div>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{tableLabel}</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              {displayFields.map((field) => {
                const isActive = orderBy === field.name;
                const label = fieldLabel(field);
                return (
                  <th
                    key={field.name}
                    scope="col"
                    className="px-3 py-2 font-medium"
                    aria-sort={onSort ? (isActive ? (order === "desc" ? "descending" : "ascending") : "none") : undefined}
                  >
                    {onSort ? (
                      <button
                        type="button"
                        onClick={() => onSort(field.name)}
                        aria-label={`Sort by ${label}`}
                        className="group flex h-6 items-center gap-1 px-1 hover:text-slate-900"
                      >
                        <span>{label}</span>
                        {/* A caret always occupies the slot for a sortable column (E-2): full
                            opacity on the active column, otherwise invisible until the header
                            is hovered/focused -- so the sort affordance is discoverable before
                            the first click, not just after it. */}
                        <span
                          aria-hidden="true"
                          className={
                            isActive
                              ? "text-slate-700"
                              : "text-slate-400 opacity-0 group-hover:opacity-100 group-focus:opacity-100"
                          }
                        >
                          {isActive && order === "desc" ? "▼" : "▲"}
                        </span>
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                );
              })}
              {onDelete && (
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">Actions</span>
              </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => {
              const rowId = rowIdentity(row);
              const rowHref = rowId !== undefined ? `/${schema}/${table}/${rowId}` : undefined;
              const label = recordLabel({ fields }, row) ?? "this row";
              return (
                <tr
                  key={rowId ?? `row-${rowIndex}`}
                  onClick={(event) => {
                    if (shouldIgnoreRowClick(event)) return;
                    if (rowId !== undefined) onRowClick?.(rowId);
                  }}
                  className={`border-b border-slate-100 hover:bg-slate-50 ${onRowClick ? "cursor-pointer" : ""}`}
                >
                  {displayFields.map((field, index) => {
                    const { content, title } = cellContent(field, row);
                    if (index === 0) {
                      return (
                        <td key={field.name} className="px-3 py-2" title={title}>
                          {rowHref !== undefined ? (
                            <RowLink to={rowHref} empty={isEmptyValue(row[field.name])} recordLabel={label}>
                              {content}
                            </RowLink>
                          ) : (
                            <span className="font-medium text-slate-900">{content}</span>
                          )}
                        </td>
                      );
                    }
                    return (
                      <td key={field.name} className="px-3 py-2" title={title}>
                        {content}
                      </td>
                    );
                  })}
                  {onDelete && (
                  <td className="px-3 py-2 text-right">
                    <RowActionsMenu row={row} label={label} onDelete={handleDeleteClick} />
                  </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
        <span role="status" aria-live="polite">
          {`${offset + 1}-${Math.min(offset + limit, total)} of ${total}`}
        </span>
        <div className="space-x-2">
          <button
            disabled={offset === 0}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            disabled={offset + limit >= total}
            onClick={() => onPageChange(offset + limit)}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
