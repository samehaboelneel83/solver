import { useMemo } from "react";
import { tableApiPath } from "../api/paths";
import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import { useSchema } from "../api/meta";
import { fieldLabel, tableLabelPlural } from "../lib/labels";
import { writeCapability } from "../types/meta";
import { useCapabilities } from "../hooks/useCapability";

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
type ChildTable = {
  schema: string;
  table: string;
  label?: string;
  label_plural?: string;
  fields: { name: string; is_fk: boolean; fk_table: string | null; label?: string }[];
};

function childRefsFrom(tables: ChildTable[], schema: string, table: string): ChildRef[] {
  const targetKey = `${schema}.${table}`;
  type RawRef = { table: ChildTable; field: ChildTable["fields"][number]; isSelfReference: boolean };
  const raw: RawRef[] = [];
  for (const t of tables) {
    for (const f of t.fields) {
      if (f.is_fk && f.fk_table === targetKey) {
        raw.push({
          table: t,
          field: f,
          isSelfReference: t.schema === schema && t.table === table,
        });
      }
    }
  }

  const refCountByTable = new Map<string, number>();
  for (const r of raw) {
    const key = `${r.table.schema}.${r.table.table}`;
    refCountByTable.set(key, (refCountByTable.get(key) ?? 0) + 1);
  }

  return raw.map((r) => {
    const key = `${r.table.schema}.${r.table.table}`;
    const needsFieldLabel = r.isSelfReference || (refCountByTable.get(key) ?? 0) > 1;
    const tableName = tableLabelPlural(r.table);
    return {
      schema: r.table.schema,
      table: r.table.table,
      field: r.field.name,
      label: needsFieldLabel ? `${tableName} via ${fieldLabel(r.field)}` : tableName,
    };
  });
}

/** "Related records" section for a detail page: every table with a foreign
 * key to this row's table, with a count of rows pointing at this specific
 * row, a link to the filtered list, and a link to create a new one prefilled
 * with this row's id. Renders nothing when no table references this one. */
export default function RelatedRecords({ schema, table, id }: RelatedRecordsProps) {
  const { data: tables } = useSchema();
  const { can } = useCapabilities();

  const children = useMemo(
    () => (tables ? childRefsFrom(tables, schema, table) : []),
    [tables, schema, table]
  );

  const counts = useQueries({
    queries: children.map((child) => ({
      queryKey: ["entities", child.schema, child.table, "related-count", child.field, id],
      queryFn: () =>
        apiFetch<ListResult>(
          `${tableApiPath(child.schema, child.table)}/?f_${child.field}=${encodeURIComponent(id)}&limit=1`
        ),
      enabled: Boolean(id),
    })),
  });

  if (children.length === 0) {
    return null;
  }

  function renderChild(child: ChildRef, index: number) {
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
    const childTable = tables?.find((t) => t.schema === child.schema && t.table === child.table);
    return (
      <li key={`${child.schema}.${child.table}.${child.field}`} className="flex items-center gap-3 text-sm">
        {/* H-9: were 20px tall with no padding -- inline-block + py-1 clears the 24px floor. */}
        <Link to={listHref} className="inline-block rounded py-1 text-blue-600 underline">
          {child.label} ({countNode})
        </Link>
        {can(writeCapability(childTable)) && (
        <Link to={newHref} className="inline-block rounded py-1 text-slate-500 underline">
          New
        </Link>
        )}
      </li>
    );
  }

  // E-6: a problem with one non-empty child and several empty ones used to
  // list every "(0)" child at equal weight, burying the one that matters.
  // A child only counts as "empty" once its count has actually resolved to
  // zero -- still-loading ("…") and errored ("?") rows stay in the main
  // list rather than being provisionally hidden.
  const nonEmpty: { child: ChildRef; index: number }[] = [];
  const empty: { child: ChildRef; index: number }[] = [];
  children.forEach((child, index) => {
    const result = counts[index];
    const isConfirmedEmpty = !result?.isError && result?.data?.total === 0;
    (isConfirmedEmpty ? empty : nonEmpty).push({ child, index });
  });
  // E-6 hides empties only when something non-empty is already on screen.
  // A brand-new parent (a user with no roles yet) has only empties: burying
  // them behind "Show N empty" hides the New link that is the next step.
  const shownEmpty = nonEmpty.length === 0 ? empty : [];
  const hiddenEmpty = nonEmpty.length === 0 ? [] : empty;

  return (
    <div className="mt-6 border-t border-slate-200 pt-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-900">Related records</h2>
      <ul className="space-y-1">
        {nonEmpty.map(({ child, index }) => renderChild(child, index))}
        {shownEmpty.map(({ child, index }) => renderChild(child, index))}
      </ul>
      {hiddenEmpty.length > 0 && (
        <details className="mt-2 text-sm text-slate-500">
          <summary className="cursor-pointer select-none hover:text-slate-700">
            Show {hiddenEmpty.length} empty
          </summary>
          <ul className="mt-1 space-y-1">{hiddenEmpty.map(({ child, index }) => renderChild(child, index))}</ul>
        </details>
      )}
    </div>
  );
}
