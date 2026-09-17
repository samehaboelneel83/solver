export type FieldType = "string" | "integer" | "number" | "boolean" | "date" | "datetime" | "uuid" | "json";

export type FieldMeta = {
  name: string;
  type: FieldType;
  required: boolean;
  writable: boolean;
  is_fk: boolean;
  fk_table: string | null;
  default?: string | number | boolean | null;
  choices?: string[] | null;
  label_field?: boolean;
  /** Human-readable name for this field, e.g. "From" for `source_entity_id`.
   * Optional so the UI still works against a backend that hasn't been
   * upgraded yet -- callers should go through `lib/labels.ts`, not read
   * this directly, so there is one place to change the fallback. */
  label?: string;
};

export type TableMeta = {
  schema: string;
  table: string;
  fields: FieldMeta[];
  /** Human-readable name for this table, e.g. "Entity type". Optional for
   * the same reason as `FieldMeta.label`. */
  label?: string;
  /** Plural human-readable name, e.g. "Entity types". Optional for the
   * same reason as `FieldMeta.label`. */
  label_plural?: string;
};
