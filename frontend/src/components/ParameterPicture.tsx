import { useMemo } from "react";
import { useEntitiesOfTypes, useParameterValues, type EntityType, type Id, type ParameterDef } from "../api/v1";
import { ShapedView, type Entry } from "./RunViews";

/** Past this many cells a picture shows the stored cells only, not every default beside them. */
export const FULL_PICTURE_CELLS = 5000;

/**
 * A number parameter drawn like an answer over the same sets (queue R17b): bars over one set, a
 * heat matrix over two, small multiples over three -- the grid's numbers as a picture, so a
 * demand's shape across the week reads at a glance.
 */
export default function ParameterPicture({ parameter, entityTypes }: { parameter: ParameterDef; entityTypes: EntityType[] }) {
  const values = useParameterValues(parameter.id);
  const axes = useEntitiesOfTypes(parameter.index_type_ids);
  const typeOf = (id: Id) => entityTypes.find((t) => t.id === id);
  const sets = parameter.index_type_ids.map((id) => typeOf(id)?.name ?? `#${id}`);
  const roles = Object.fromEntries(parameter.index_type_ids.map((id) => [typeOf(id)?.name ?? `#${id}`, typeOf(id)?.role ?? "other"]));

  const { entries, order, labels, full } = useMemo(() => {
    const byType = parameter.index_type_ids.map((t) => axes.items.filter((e) => e.entity_type_id === t));
    const keyOf = new Map(axes.items.map((e) => [e.id, e.key]));
    const order: Record<string, string[]> = {};
    const labels: Record<string, Record<string, string>> = {};
    byType.forEach((list, i) => {
      order[sets[i]] = list.map((e) => e.key);
      labels[sets[i]] = Object.fromEntries(list.filter((e) => e.label).map((e) => [e.key, e.label as string]));
    });
    const stored = new Map((values.data?.cells ?? []).map((c) => [c.entity_ids.join(","), Number(c.value ?? parameter.default_value)]));
    const total = byType.reduce((n, list) => n * list.length, 1);
    const full = total <= FULL_PICTURE_CELLS;
    const entries: Entry[] = [];
    if (full) {
      // Every cell, the empty ones at the default -- the picture of what a run reads.
      const walk = (i: number, ids: Id[]) => {
        if (i === byType.length) {
          entries.push({ index: ids.map((id) => keyOf.get(id) ?? String(id)), value: stored.get(ids.join(",")) ?? parameter.default_value });
          return;
        }
        for (const e of byType[i]) walk(i + 1, [...ids, e.id]);
      };
      walk(0, []);
    } else {
      for (const c of values.data?.cells ?? [])
        entries.push({ index: c.entity_ids.map((id) => keyOf.get(id) ?? String(id)), value: Number(c.value ?? parameter.default_value) });
    }
    return { entries, order, labels, full };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [axes.items, values.data, parameter]);

  if (values.isLoading || axes.isLoading) return null;
  return (
    <ShapedView
      name={parameter.name}
      shape={{ sets, kind: "continuous", roles, hasAmounts: true }}
      entries={entries}
      order={order}
      labels={labels}
      places={{}}
      count={full ? `${entries.length} cells` : `${entries.length} stored cells (the others are ${parameter.default_value})`}
      empty="No cells yet."
    />
  );
}
