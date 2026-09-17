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
 * per FK field (a self-reference like `parent_type_id` is included and
 * labelled with the field name so it isn't confused with the table itself). */
function childRefsFrom(tables: { schema: string; table: string; fields: { name: string; is_fk: boolean; fk_table: string | null }[] }[], schema: string, table: string): ChildRef[] {
  const targetKey = `${schema}.${table}`;
  const refs: ChildRef[] = [];
  for (const t of tables) {
    for (const f of t.fields) {
      if (f.is_fk && f.fk_table === targetKey) {
        const isSelfReference = t.schema === schema && t.table === table;
        refs.push({
          schema: t.schema,
          table: t.table,
          field: f.name,
          label: isSelfReference ? `${t.table} via ${f.name}` : t.table,
        });
      }
    }
  }
  return refs;
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
          const countLabel = count === undefined ? "…" : count;
          const listHref = `/${child.schema}/${child.table}?f_${child.field}=${encodeURIComponent(id)}`;
          const newHref = `/${child.schema}/${child.table}/new?${child.field}=${encodeURIComponent(id)}`;
          return (
            <li key={`${child.schema}.${child.table}.${child.field}`} className="flex items-center gap-3 text-sm">
              <Link to={listHref} className="text-blue-600 underline">
                {child.label} ({countLabel})
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
