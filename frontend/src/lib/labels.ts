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
