import { useState } from "react";
import type { EmptyRange } from "../api/v1";

/** How many places a group names before "and N more". */
const NAMED = 5;

export type EmptyGroup = { rule: string; kind: string; places: string[] };

/** One group per rule and kind of range: a rule filtered to a few sites matches nobody at all the
 * others, and one line per site would bury everything else on the page. */
export function groupEmptyRanges(items: EmptyRange[], name: (key: string) => string = (k) => k): EmptyGroup[] {
  const groups = new Map<string, EmptyGroup>();
  for (const item of items) {
    const id = `${item.constraint_id}\u0000${item.kind}`;
    const group = groups.get(id) ?? { rule: item.constraint_id, kind: item.kind, places: [] };
    const keys = Object.values(item.index);
    if (keys.length) group.places.push(keys.map(name).join(" · "));
    groups.set(id, group);
  }
  return [...groups.values()];
}

function Group({ group }: { group: EmptyGroup }) {
  const [all, setAll] = useState(false);
  const { places } = group;
  const shown = all ? places : places.slice(0, NAMED);
  return (
    <li>
      <span className="font-mono">{group.rule}</span>
      {group.kind === "forall" ? (
        " never applied to anyone"
      ) : places.length === 0 ? (
        " counted nobody"
      ) : places.length === 1 ? (
        ` counted nobody at ${places[0]}`
      ) : (
        <>
          {` counted nobody at ${places.length} places: `}
          <span className="text-slate-600">{shown.join(", ")}</span>
          {places.length > NAMED && (
            <button type="button" className="ml-1 text-blue-700 underline" onClick={() => setAll(!all)}>
              {all ? "show fewer" : `and ${places.length - NAMED} more`}
            </button>
          )}
          <span className="block text-xs text-slate-500">
            Expected when the rule only concerns some of them (a filter most do not meet); otherwise check the data.
          </span>
        </>
      )}
    </li>
  );
}

/** The rules that ranged over nobody, grouped, for the model editor and a run. */
export default function EmptyRanges({ items, name }: { items: EmptyRange[]; name?: (key: string) => string }) {
  return (
    <ul className="space-y-1 text-sm text-slate-800">
      {groupEmptyRanges(items, name).map((g) => (
        <Group key={`${g.rule}:${g.kind}`} group={g} />
      ))}
    </ul>
  );
}
