import type { FieldMeta, TableMeta } from "../types/meta";

/**
 * Human-readable name for a table, e.g. "Entity type" for `entity_type`.
 * Falls back to the raw table name so the UI still renders something
 * sensible if the backend hasn't sent a `label` yet (B-1).
 */
export function tableLabel(table: Pick<TableMeta, "table" | "label">): string {
  return table.label || table.table;
}

/**
 * Plural human-readable name for a table, e.g. "Entity types". Falls back
 * to the singular label, then the raw table name (B-1).
 */
export function tableLabelPlural(table: Pick<TableMeta, "table" | "label" | "label_plural">): string {
  return table.label_plural || table.label || table.table;
}

/**
 * Human-readable name for a field, e.g. "From" for `source_entity_id`.
 * Falls back to the raw field name (B-1).
 */
export function fieldLabel(field: Pick<FieldMeta, "name" | "label">): string {
  return field.label || field.name;
}

/**
 * Lower-cases just the first character, so a table label like "Entity type"
 * reads naturally mid-sentence: "New entity type" rather than the shoutier
 * "New Entity type".
 */
export function lowerFirst(value: string): string {
  return value ? value[0].toLowerCase() + value.slice(1) : value;
}

/**
 * A human-readable name for one record, e.g. "acme — Acme Corp" or just
 * "acme". Mirrors the backend's own `_default_label` (used for FK-dropdown
 * option labels): prefers a "code — name" pair when both are present,
 * otherwise the first non-empty value among the table's `label_field`
 * columns, in the order the backend reports them.
 *
 * Used by the edit page's heading (C-6): "Edit entity type" is identical
 * for every row, so the heading needs the record's own name, not just the
 * table's.  Returns `undefined` when nothing usable is available (no
 * `label_field` columns, or the record hasn't loaded yet) so callers can
 * fall back to the generic table label.
 */
export function recordLabel(
  table: Pick<TableMeta, "fields">,
  record: Record<string, unknown> | undefined | null
): string | undefined {
  if (!record) return undefined;
  const labelFieldNames = table.fields.filter((f) => f.label_field).map((f) => f.name);
  if (labelFieldNames.length === 0) return undefined;

  const code = labelFieldNames.includes("code") ? record.code : undefined;
  const name = labelFieldNames.includes("name") ? record.name : undefined;
  if (code && name) return `${code} — ${name}`;

  for (const fieldName of labelFieldNames) {
    const value = record[fieldName];
    if (value !== null && value !== undefined && value !== "") return String(value);
  }
  return undefined;
}
