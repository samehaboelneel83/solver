import { useMemo, useState } from "react";
import { formatApiError } from "../api/errors";
import {
  useEntities,
  useEntitiesOfTypes,
  useParameterValues,
  usePutParameterValues,
  type Entity,
  type EntityType,
  type Id,
  type ParameterDef,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useToast } from "./ToastProvider";
import { INPUT_CLASS } from "./attrTypes";

/**
 * The values of a parameter whose values are entities (queue R20b):
 * `preferred_shift[employee, day] = shift`. Each cell is a dropdown of the
 * value type's entities; empty is no value (an entity has no default).
 * One or two index types draw as a grid, rows by columns; more as the list
 * of stored cells with a line to add one.
 */
export default function EntityParameterGrid({ parameter, entityTypes }: { parameter: ParameterDef; entityTypes: EntityType[] }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const toast = useToast();
  const values = useParameterValues(parameter.id);
  const put = usePutParameterValues();
  const choices = useEntities((parameter.value_type_id as Id | null) ?? null, { family: true, limit: 500 });
  const axes = useEntitiesOfTypes(parameter.index_type_ids);
  const [draft, setDraft] = useState<(Id | "")[]>(() => parameter.index_type_ids.map(() => ""));

  const held = useMemo(() => {
    const map = new Map<string, Id>();
    for (const cell of values.data?.cells ?? []) {
      if (cell.value_entity_id != null) map.set(cell.entity_ids.join(","), cell.value_entity_id);
    }
    return map;
  }, [values.data]);
  const typeName = (id: Id | null | undefined) => entityTypes.find((t) => t.id === id)?.name ?? "entity";
  const options = choices.data?.items ?? [];
  const label = (e: Entity) => (e.label ? `${e.key} — ${e.label}` : e.key);

  async function save(entityIds: Id[], value: Id | "") {
    try {
      await put.mutateAsync({ id: parameter.id, cells: [{ entity_ids: entityIds, value_entity_id: value === "" ? null : value }] });
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  const select = (entityIds: Id[], name: string) => (
    <select
      aria-label={name}
      className={`${INPUT_CLASS} min-w-[7rem] py-1 text-xs`}
      value={held.get(entityIds.join(",")) ?? ""}
      disabled={!canEdit || put.isPending}
      onChange={(e) => save(entityIds, e.target.value === "" ? "" : (Number(e.target.value) as Id))}
    >
      <option value="">—</option>
      {options.map((e) => (
        <option key={e.id} value={e.id}>
          {label(e)}
        </option>
      ))}
    </select>
  );

  if (values.isLoading || axes.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  // One list per index position, in the parameter's order (a type may repeat).
  const lists = parameter.index_type_ids.map((t) => axes.items.filter((e) => e.entity_type_id === t));
  const intro = (
    <p className="mb-3 text-sm text-slate-600">
      Each cell names one <span className="font-mono">{typeName(parameter.value_type_id)}</span>; leave it empty for none.
    </p>
  );

  if (lists.length <= 2) {
    const rows = lists[0] ?? [];
    const columns = lists.length === 2 ? lists[1] : [null];
    return (
      <div>
        {intro}
        <div className="overflow-x-auto">
          <table className="text-sm">
            {lists.length === 2 && (
              <thead>
                <tr>
                  <th />
                  {columns.map((c) => (
                    <th key={c!.id} scope="col" className="px-2 py-1 text-left font-medium text-slate-700">
                      {c!.key}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <th scope="row" className="px-2 py-1 text-left font-medium text-slate-700">
                    {r.key}
                  </th>
                  {columns.map((c) => {
                    const ids = c ? [r.id, c.id] : [r.id];
                    return (
                      <td key={c ? c.id : "value"} className="px-1 py-1">
                        {select(ids, `${parameter.name}[${r.key}${c ? `, ${c.key}` : ""}]`)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Three index types or more: the stored cells, and a line to set one.
  const keyOf = (id: Id) => lists.flat().find((e) => e.id === id)?.key ?? String(id);
  return (
    <div>
      {intro}
      <ul className="mb-3 space-y-1 text-sm">
        {(values.data?.cells ?? []).map((cell) => (
          <li key={cell.entity_ids.join(",")} className="flex items-center gap-2">
            <span className="font-mono">
              {parameter.name}[{cell.entity_ids.map(keyOf).join(", ")}]
            </span>
            {select(cell.entity_ids, `${parameter.name}[${cell.entity_ids.map(keyOf).join(", ")}]`)}
          </li>
        ))}
      </ul>
      {canEdit && (
        <div className="flex flex-wrap items-end gap-2">
          {lists.map((list, k) => (
            <select
              key={k}
              aria-label={`${typeName(parameter.index_type_ids[k])} (position ${k + 1})`}
              className={`${INPUT_CLASS} w-auto py-1 text-xs`}
              value={draft[k]}
              onChange={(e) => setDraft(draft.map((d, j) => (j === k ? (e.target.value === "" ? "" : (Number(e.target.value) as Id)) : d)))}
            >
              <option value="">choose…</option>
              {list.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.key}
                </option>
              ))}
            </select>
          ))}
          {draft.every((d) => d !== "") && select(draft as Id[], `${parameter.name} new cell`)}
        </div>
      )}
    </div>
  );
}
