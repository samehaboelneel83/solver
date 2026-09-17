import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import { useSchema } from "../api/meta";

type ChildRef = {
  schema: string;
  table: string;
  field: string;
  label: string;
};

type RelatedRecordsProps = {
  schema: string;
  table: string;
  id: string;
};

/** Every table that has a foreign key pointing at `<schema>.<table>`, one row
 * per FK field. A row is labelled `<table> via <field>` instead of plain
 * `<table>` whenever the field name is needed to tell rows apart: a
 * self-reference like `parent_type_id` (always ambiguous with the parent
 * table itself), or a child table with more than one FK field pointing at
 * this parent (e.g. `relationship.source_entity_id` and
 * `relationship.target_entity_id` both -> `entity`). */
function childRefsFrom(tables: { schema: string; table: string; fields: { name: string; is_fk: boolean; fk_table: string | null }[] }[], schema: string, table: string): ChildRef[] {
  const targetKey = `${schema}.${table}`;
  type RawRef = { schema: string; table: string; field: string; isSelfReference: boolean };
  const raw: RawRef[] = [];
  for (const t of tables) {
    for (const f of t.fields) {
      if (f.is_fk && f.fk_table === targetKey) {
        raw.push({
          schema: t.schema,
          table: t.table,
          field: f.name,
          isSelfReference: t.schema === schema && t.table === table,
        });
      }
    }
  }

  const refCountByTable = new Map<string, number>();
  for (const r of raw) {
    const key = `${r.schema}.${r.table}`;
    refCountByTable.set(key, (refCountByTable.get(key) ?? 0) + 1);
  }

  return raw.map((r) => {
    const key = `${r.schema}.${r.table}`;
    const needsFieldLabel = r.isSelfReference || (refCountByTable.get(key) ?? 0) > 1;
    return {
      schema: r.schema,
      table: r.table,
      field: r.field,
      label: needsFieldLabel ? `${r.table} via ${r.field}` : r.table,
    };
  });
}

/** "Related records" section for a detail page: every table with a foreign
 * key to this row's table, with a count of rows pointing at this specific
 * row, a link to the filtered list, and a link to create a new one prefilled
 * with this row's id. Renders nothing when no table references this one. */
export default function RelatedRecords({ schema, table, id }: RelatedRecordsProps) {
  const { data: tables } = useSchema();

  const children = useMemo(
    () => (tables ? childRefsFrom(tables, schema, table) : []),
    [tables, schema, table]
  );

  const counts = useQueries({
    queries: children.map((child) => ({
      queryKey: ["entities", child.schema, child.table, "related-count", child.field, id],
      queryFn: () =>
        apiFetch<ListResult>(
          `/api/${child.schema}/${child.table}/?f_${child.field}=${encodeURIComponent(id)}&limit=1`
        ),
      enabled: Boolean(id),
    })),
  });

  if (children.length === 0) {
    return null;
  }

  return (
    <div className="mt-6 border-t border-slate-200 pt-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-900">Related records</h2>
      <ul className="space-y-1">
        {children.map((child, index) => {
          const result = counts[index];
          const count = result?.data?.total;
          const countNode = result?.isError ? (
            <span title="Count unavailable">?</span>
          ) : count === undefined ? (
            "…"
          ) : (
            count
          );
          const listHref = `/${child.schema}/${child.table}?f_${child.field}=${encodeURIComponent(id)}`;
          const newHref = `/${child.schema}/${child.table}/new?${child.field}=${encodeURIComponent(id)}`;
          return (
            <li key={`${child.schema}.${child.table}.${child.field}`} className="flex items-center gap-3 text-sm">
              <Link to={listHref} className="text-blue-600 underline">
                {child.label} ({countNode})
              </Link>
              <Link to={newHref} className="text-slate-500 underline">
                New
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
