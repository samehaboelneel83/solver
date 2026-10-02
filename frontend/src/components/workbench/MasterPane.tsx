import { useState } from "react";
import { apiFetch } from "../../api/client";
import { formatAttrValue } from "../AttrsForm";
import RecordGrid from "../RecordGrid";
import GeoMap, { type GeoMark } from "../map/GeoMap";
import { asGeometry } from "../../lib/geoShape";
import { useCapabilities } from "../../hooks/useCapability";
import { useChildren, useGroups, usePlace, type ChildGroup, type TreeRecord, type WorkbenchSchema } from "../../api/workbench";
import { useEntityRecord, useEntityType, type EntityType, type Id } from "../../api/v1";
import type { TreeSelection } from "./WorkbenchTree";

export type View = "cards" | "grid" | "map";

const TAB = "rounded-t-md border-b-2 px-3 py-1.5 text-sm";

function Cards({
  type,
  items,
  problems,
  onOpen,
}: {
  type: EntityType;
  items: TreeRecord[];
  problems: Record<string, string[]>;
  onOpen: (id: Id) => void;
}) {
  // The first three fields a person reads -- not a shape, which says nothing as text.
  const shown = type.attributes.filter((a) => a.data_type !== "geometry").slice(0, 3);
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label={`${type.name} records`}>
      {items.map((r) => {
        const codes = problems[String(r.id)];
        return (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onOpen(r.id)}
              className={`h-full w-full rounded-lg border bg-white p-3 text-left shadow-sm hover:border-blue-400 ${
                codes?.length ? "border-amber-300" : "border-slate-200"
              } ${r.active ? "" : "opacity-60"}`}
            >
              <span className="block font-medium text-slate-900">{r.label || r.key}</span>
              <span className="block font-mono text-xs text-slate-500">{r.key}</span>
              <dl className="mt-2 space-y-0.5 text-xs">
                {shown.map((a) => (
                  <div key={a.id} className="flex gap-1">
                    <dt className="text-slate-500">{a.name}:</dt>
                    <dd className="truncate text-slate-800">{formatAttrValue(r.attrs?.[a.name])}</dd>
                  </div>
                ))}
              </dl>
              <span className="mt-2 flex flex-wrap gap-1 text-xs">
                {r.children > 0 && <span className="rounded bg-slate-100 px-1.5 text-slate-600">{r.children} under it</span>}
                {!r.active && <span className="rounded bg-slate-100 px-1.5 text-slate-600">switched off</span>}
                {placed(type) &&
                  !type.attributes.some((a) => a.data_type === "geometry" && asGeometry(r.attrs?.[a.name])) && (
                    <span className="rounded bg-sky-50 px-1.5 text-sky-800">no place yet</span>
                  )}
                {codes?.length ? <span className="rounded bg-amber-100 px-1.5 text-amber-800">needs a look</span> : null}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** Whether a kind has a shape field, so its records can be shown on a map. */
function placed(type: EntityType | undefined): boolean {
  return (type?.attributes ?? []).some((a) => a.data_type === "geometry");
}

/** The listed records on the map, over their parent's shape; a record's mark opens it. */
function ListMap({ type, items, parent, onOpen }: { type: EntityType; items: TreeRecord[]; parent: Id | null; onOpen: (id: Id) => void }) {
  const parentRecord = useEntityRecord(parent);
  const parentType = useEntityType(parentRecord.data?.entity_type_id ?? null);
  const fields = type.attributes.filter((a) => a.data_type === "geometry").map((a) => a.name);
  const marks: GeoMark[] = [];
  let without = 0;
  for (const p of (parentType.data?.attributes ?? []).filter((a) => a.data_type === "geometry")) {
    const g = asGeometry(parentRecord.data?.attrs?.[p.name]);
    if (g) marks.push({ id: `parent-${p.name}`, geometry: g, colour: "#94a3b8", fill: 0.08, size: 4, layer: "around",
      title: `${parentRecord.data?.label || parentRecord.data?.key} (${p.name})` });
  }
  for (const r of items) {
    const g = fields.map((f) => asGeometry(r.attrs?.[f])).find((x) => x);
    if (!g) { without += 1; continue; }
    marks.push({ id: String(r.id), geometry: g, colour: r.active ? "#2563eb" : "#94a3b8", size: 6, fill: 0.25, layer: type.name,
      title: `${r.label || r.key}${r.label ? ` (${r.key})` : ""}`, label: r.label || r.key, pickable: true });
  }
  return (
    <GeoMap
      marks={marks}
      onPick={(id) => onOpen(Number(id))}
      caption={[`${marks.filter((m) => m.pickable).length} on the map — click one to open it`,
        without ? `${without} without a place yet (open one, then Location)` : null].filter(Boolean).join(" · ")}
    />
  );
}

function List({
  domainId,
  schema,
  group,
  parent,
  parentKey,
  kindId,
  view,
  problems,
  onOpen,
  showInactive,
  adding,
  setAdding,
}: {
  domainId: Id;
  schema: WorkbenchSchema;
  group: string;
  parent: Id | null;
  parentKey: string | null;
  kindId: Id;
  view: View;
  problems: Record<string, string[]>;
  onOpen: (id: Id) => void;
  showInactive: boolean;
  adding: boolean;
  setAdding: (on: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const list = useChildren(domainId, group, parent, { q, limit: 200 });
  const type = useEntityType(kindId);
  const edge = schema.edges.find((e) => e.group_key === group);
  if (!type.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const items = (list.data?.items ?? []).filter((r) => showInactive || r.active);
  // A new record under this parent: a reference field filled with its key, or a hierarchy link made after.
  const prefill = edge?.group_key.startsWith("ref:") && parentKey ? { [edge.field]: parentKey } : undefined;
  const afterCreate =
    edge?.group_key.startsWith("rel:") && parent != null
      ? async (created: { id: Id }) => {
          await apiFetch("/api/v1/relationships", {
            method: "POST",
            body: JSON.stringify({ relationship_type_id: edge.relationship_type_id, from_entity_id: parent, to_entity_id: created.id }),
          });
        }
      : undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`wb-filter-${group}`}>
          Filter {type.data.name} records
        </label>
        <input
          id={`wb-filter-${group}`}
          className="w-48 rounded-md border border-slate-300 px-2 py-1 text-sm"
          placeholder={`Filter ${type.data.name}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-xs text-slate-500">
          {list.data ? `${items.length} of ${list.data.total}` : ""}
          {prefill && ` · new rows get ${edge?.field} = ${parentKey}`}
        </span>
      </div>
      {list.isError && <p className="text-sm text-red-700">Could not load these records.</p>}
      {view === "map" && !adding && placed(type.data) ? (
        <ListMap type={type.data} items={items} parent={parent} onOpen={onOpen} />
      ) : view === "grid" || adding ? (
        <RecordGrid
          key={`${group}-${parent}-${q}-${adding}`}
          type={type.data}
          records={items}
          prefill={prefill}
          afterCreate={afterCreate}
          startWithNew={adding}
          onOpen={onOpen}
          onDone={adding ? () => setAdding(false) : undefined}
        />
      ) : items.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          No {type.data.name} records here yet.
        </p>
      ) : (
        <Cards type={type.data} items={items} problems={problems} onOpen={onOpen} />
      )}
    </div>
  );
}

/**
 * The middle of the workbench: the records under what the tree has selected, one tab per kind that
 * can sit there, as cards or as an editable grid. "+ New" opens a row already placed under the
 * selected record.
 */
export default function MasterPane({
  domainId,
  schema,
  selection,
  tab,
  setTab,
  view,
  setView,
  problems,
  onOpen,
  showInactive,
}: {
  domainId: Id;
  schema: WorkbenchSchema;
  selection: TreeSelection | null;
  tab: string | null;
  setTab: (group: string) => void;
  view: View;
  setView: (v: View) => void;
  problems: Record<string, string[]>;
  onOpen: (id: Id) => void;
  showInactive: boolean;
}) {
  const { can } = useCapabilities();
  const [adding, setAdding] = useState(false);
  const recordId = selection?.kind === "record" ? selection.id : null;
  const record = useEntityRecord(recordId);
  const groups = useGroups(domainId, recordId);
  // A record nothing can sit under (a truck): show the list it is in, so its siblings can be added to.
  const leaf = groups.isSuccess && (groups.data?.groups.length ?? 0) === 0;
  const place = usePlace(domainId, recordId, leaf);

  let tabs: ChildGroup[] = [];
  let current: { group: string; kindId: Id; title: string } | null = null;
  if (!selection) {
    current = null;
  } else if (selection.kind === "root") {
    const kind = schema.kinds.find((k) => k.id === selection.kindId);
    current = { group: `root:${selection.kindId}`, kindId: selection.kindId, title: `${kind?.name ?? ""} at the top` };
  } else {
    tabs = groups.data?.groups ?? [];
    const pick = tabs.find((g) => g.group === tab) ?? tabs.find((g) => g.count > 0) ?? tabs[0];
    if (pick) current = { group: pick.group, kindId: pick.kind_id, title: `${pick.kind} under ${record.data?.label || record.data?.key || ""}` };
    else if (leaf && place.data) {
      const kind = schema.kinds.find((k) => k.id === place.data.kind_id)?.name ?? "";
      const under = place.data.parent ? ` under ${place.data.parent.label || place.data.parent.key}` : " at the top";
      current = { group: place.data.group, kindId: place.data.kind_id, title: `${kind}${under}` };
    }
  }
  const siblingsOf = leaf && place.data ? place.data.parent : null;
  const listType = useEntityType(current?.kindId ?? null);
  if (!selection) {
    return <p className="p-6 text-sm text-slate-500">Choose a record or a kind in the tree.</p>;
  }

  return (
    <section aria-label="Records under the selection" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">{current?.title ?? "Nothing can sit under this record"}</h2>
        {current && (
          <div className="flex items-center gap-2">
            <div role="group" aria-label="Show as" className="inline-flex overflow-hidden rounded-md border border-slate-300 text-sm">
              {(["cards", "grid", ...(placed(listType.data) ? (["map"] as const) : [])] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={view === v}
                  onClick={() => setView(v)}
                  className={`px-3 py-1 ${view === v ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
                >
                  {v === "cards" ? "Cards" : v === "grid" ? "Grid" : "Map"}
                </button>
              ))}
            </div>
            {can("domain.edit") && (
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="rounded-md bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700"
              >
                + New {schema.kinds.find((k) => k.id === current?.kindId)?.name}
              </button>
            )}
          </div>
        )}
      </div>
      {tabs.length > 1 && (
        <div role="tablist" aria-label="Kinds under this record" className="flex flex-wrap gap-1 border-b border-slate-200">
          {tabs.map((g) => (
            <button
              key={g.group}
              role="tab"
              type="button"
              aria-selected={g.group === current?.group}
              onClick={() => {
                setAdding(false);
                setTab(g.group);
              }}
              className={`${TAB} ${g.group === current?.group ? "border-blue-600 font-medium text-blue-800" : "border-transparent text-slate-600 hover:text-slate-900"}`}
            >
              {g.kind} <span className="text-slate-400">({g.count})</span>
              {tabs.filter((t) => t.kind === g.kind).length > 1 && <span className="ml-1 text-xs">by {g.field}</span>}
            </button>
          ))}
        </div>
      )}
      {leaf && current && (
        <p className="text-xs text-slate-500">
          Nothing sits under a {schema.kinds.find((k) => k.id === record.data?.entity_type_id)?.name}; these are the records
          beside it.
        </p>
      )}
      {current && (
        <List
          key={`${current.group}-${leaf ? siblingsOf?.id : recordId}`}
          domainId={domainId}
          schema={schema}
          group={current.group}
          parent={leaf ? (siblingsOf?.id ?? null) : recordId}
          parentKey={leaf ? (siblingsOf?.key ?? null) : (record.data?.key ?? null)}
          kindId={current.kindId}
          view={view}
          problems={problems}
          onOpen={onOpen}
          showInactive={showInactive}
          adding={adding}
          setAdding={setAdding}
        />
      )}
    </section>
  );
}
