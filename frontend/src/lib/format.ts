import type { FieldMeta } from "../types/meta";

/**
 * A formatted table cell: the text to render, an optional `title` (the
 * un-formatted/raw value, shown on hover -- e.g. the full ISO timestamp
 * behind a "Sep 17, 2026, 12:37 PM"), and an optional `ariaLabel` that
 * overrides the accessible name when the visible text is a symbol rather
 * than a word (e.g. "✓" reads as "Yes" to a screen reader, not "check
 * mark").
 */
export type FormattedCell = {
  text: string;
  title?: string;
  ariaLabel?: string;
};

// `undefined` locale = the reader's own browser/OS locale; no `timeZone`
// override = the reader's own local time zone (E-3: timestamps must stop
// being raw UTC strings the reader has to mentally convert).
const DATETIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

// Date-only fields (no time component) are pinned to UTC when formatting:
// a bare calendar date like "2026-09-17" has no time-of-day to convert, and
// interpreting it in the reader's local zone risks shifting it to the
// adjacent day. Formatting the same UTC-anchored instant back out in UTC
// keeps the calendar date stable everywhere.
const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeZone: "UTC",
});

const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})/;

function isEmpty(value: unknown): value is null | undefined | "" {
  return value === null || value === undefined || value === "";
}

/**
 * Human-readable rendering for one table cell, keyed off the field's
 * declared type (E-3, E-5):
 *  - `datetime` -> localized date + time via `Intl.DateTimeFormat`, full
 *    ISO string kept in `title`.
 *  - `date` -> localized date only (no time), ISO string kept in `title`.
 *  - `boolean` -> "✓"/"—" with an accessible name of "Yes"/"No" (never the
 *    bare words "true"/"false").
 *  - everything else (including `uuid`) -> unchanged, via `String(value)`.
 */
export function formatCellValue(
  field: Pick<FieldMeta, "type">,
  value: unknown
): FormattedCell {
  if (isEmpty(value)) return { text: "" };

  if (field.type === "datetime" && typeof value === "string") {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return { text: DATETIME_FORMATTER.format(date), title: value };
    }
  }

  if (field.type === "date" && typeof value === "string") {
    const match = DATE_ONLY_PATTERN.exec(value);
    if (match) {
      const [, year, month, day] = match;
      const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
      if (!Number.isNaN(date.getTime())) {
        return { text: DATE_FORMATTER.format(date), title: value };
      }
    }
  }

  if (field.type === "boolean" && typeof value === "boolean") {
    return value ? { text: "✓", ariaLabel: "Yes" } : { text: "—", ariaLabel: "No" };
  }

  if (typeof value === "object" && value !== null && ["Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"].includes(String((value as { type?: unknown }).type))) {
    // A shape: named, never printed as its coordinates.
    const count = JSON.stringify((value as { coordinates?: unknown }).coordinates ?? []).match(/\[-?[\d.e+-]+,-?[\d.e+-]+/g)?.length ?? 0;
    return { text: `${(value as { type: string }).type}, ${count} positions`, title: "GeoJSON shape" };
  }

  if (typeof value === "object") {
    return { text: JSON.stringify(value) };
  }

  return { text: String(value) };
}
