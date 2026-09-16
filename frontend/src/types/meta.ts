export type FieldType = "string" | "integer" | "number" | "boolean" | "date" | "datetime" | "uuid" | "json";

export type FieldMeta = {
  name: string;
  type: FieldType;
  required: boolean;
  writable: boolean;
  is_fk: boolean;
  fk_table: string | null;
};

export type TableMeta = {
  schema: string;
  table: string;
  fields: FieldMeta[];
};
