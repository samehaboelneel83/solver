import { DragEvent, useState } from "react";
import {
  useChildren,
  useGroups,
  type ChildGroup,
  type TreeRecord,
  type WorkbenchSchema,
} from "../../api/workbench";
import type { Id } from "../../api/v1";

/** What the tree reports up: the record or the top-level list chosen, and a record dropped on another. */
export type TreeSelection = { kind: "record"; id: Id } | { kind: "root"; kindId: Id };

export type TreeProps = {
  domainId: Id;
  schema: WorkbenchSchema;
  problems: Record<string, string[]>;
  selected: TreeSelection | null;
  onSelect: (s: TreeSelection) => void;
  expanded: ReadonlySet<string>;
  toggle: (node: string, open?: boolean) => void;
  /** A record dropped on another: place it under it. */
  onMove?: (moved: TreeRecord, onto: TreeRecord) => void;
  showInactive: boolean;
};

export const rootNode = (kindId: Id) => `g:root:${kindId}`;
export const recordNode = (id: Id) => `r:${id}`;
export const groupNode = (group: string, parent: Id) => `g:${group}:${parent}`;

const WORDS: Record<string, string> = {
  loop: "chain loops back on itself",
  too_deep: "deeper than the limit",
  outside_tree: "not placed in its tree",
  inactive_target: "refers to a switched-off record",
};

function Dot({ codes }: { codes?: string[] }) {
  if (!codes?.length) return null;
  const bad = codes.includes("loop");
  return (
    <span
      className={`ml-1 inline-block h-2 w-2 rounded-full ${bad ? "bg-red-600" : "bg-amber-500"}`}
      title={codes.map((c) => WORDS[c] ?? c).join("; ")}
      aria-label={`Problem: ${codes.map((c) => WORDS[c] ?? c).join("; ")}`}
      role="img"
    />
  );
}

const ROW = "flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-sm";

function Toggle({ open, count, label, onClick }: { open: boolean; count: number; label: string; onClick: () => void }) {
  if (count === 0) return <span className="inline-block w-4" />;
  return (
    <button
      type="button"
      className="w-4 shrink-0 text-slate-500 hover:text-slate-900"
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
      onClick={onClick}
    >
      {open ? "▾" : "▸"}
    </button>
  );
}

function Records({ props, group, parent }: { props: TreeProps; group: string; parent: Id | null }) {
  const [limit, setLimit] = useState(100);
  const list = useChildren(props.domainId, group, parent, { limit });
  if (list.isLoading) return <li className="pl-5 text-xs text-slate-400">Loading…</li>;
  if (list.isError) return <li className="pl-5 text-xs text-red-700">Could not load.</li>;
  const items = (list.data?.items ?? []).filter((r) => props.showInactive || r.active);
  return (
    <>
      {items.map((r) => (
        <RecordItem key={r.id} props={props} record={r} />
      ))}
      {(list.data?.total ?? 0) > (list.data?.items.length ?? 0) && (
        <li className="pl-5">
          <button type="button" className="text-xs text-blue-700 underline" onClick={() => setLimit(limit + 100)}>
            {(list.data?.total ?? 0) - (list.data?.items.length ?? 0)} more…
          </button>
        </li>
      )}
    </>
  );
}

function Groups({ props, parent }: { props: TreeProps; parent: TreeRecord }) {
  const groups = useGroups(props.domainId, parent.id);
  const filled = (groups.data?.groups ?? []).filter((g) => g.count > 0);
  if (groups.isLoading) return <li className="pl-5 text-xs text-slate-400">Loading…</li>;
  // One kind below: its records directly. Several: one branch per kind, so they do not mix.
  if (filled.length === 1) return <Records props={props} group={filled[0].group} parent={parent.id} />;
  return (
    <>
      {filled.map((g) => (
        <GroupItem key={g.group} props={props} group={g} parent={parent.id} />
      ))}
    </>
  );
}

function GroupItem({ props, group, parent }: { props: TreeProps; group: ChildGroup; parent: Id }) {
  const node = groupNode(group.group, parent);
  const open = props.expanded.has(node);
  const label = `${group.kind} by ${group.field}`;
  return (
    <li>
      <div className={ROW}>
        <Toggle open={open} count={group.count} label={label} onClick={() => props.toggle(node)} />
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {group.kind} <span className="font-normal normal-case">({group.count})</span>
        </span>
      </div>
      {open && (
        <ul className="ml-3 border-l border-slate-200 pl-2">
          <Records props={props} group={group.group} parent={parent} />
        </ul>
      )}
    </li>
  );
}

function RecordItem({ props, record }: { props: TreeProps; record: TreeRecord }) {
  const node = recordNode(record.id);
  const open = props.expanded.has(node);
  const chosen = props.selected?.kind === "record" && props.selected.id === record.id;
  const [over, setOver] = useState(false);
  const name = record.label ? record.label : record.key;
  const kindName = props.schema.kinds.find((k) => k.id === record.entity_type_id)?.name ?? "";

  function canTake(event: DragEvent) {
    return event.dataTransfer.types.includes("application/x-workbench-record");
  }
  return (
    <li id={`wb-${record.id}`}>
      <div
        className={`${ROW} ${chosen ? "bg-blue-100 font-medium text-blue-900" : "hover:bg-slate-100"} ${over ? "ring-2 ring-blue-400" : ""} ${
          record.active ? "" : "opacity-60"
        }`}
        draggable={!!props.onMove}
        onDragStart={(e) => {
          e.dataTransfer.setData("application/x-workbench-record", JSON.stringify(record));
          e.dataTransfer.effectAllowed = "move";
        }}
        onDragOver={(e) => {
          if (!props.onMove || !canTake(e)) return;
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          setOver(false);
          const raw = e.dataTransfer.getData("application/x-workbench-record");
          if (!raw || !props.onMove) return;
          e.preventDefault();
          const moved = JSON.parse(raw) as TreeRecord;
          if (moved.id !== record.id) props.onMove(moved, record);
        }}
      >
        <Toggle open={open} count={record.children} label={record.key} onClick={() => props.toggle(node)} />
        <button
          type="button"
          className="min-w-0 flex-1 truncate text-left"
          aria-current={chosen ? "true" : undefined}
          title={`${kindName} ${record.key}`}
          onClick={() => props.onSelect({ kind: "record", id: record.id })}
        >
          {name}
          {record.label && <span className="ml-1 font-mono text-xs text-slate-500">{record.key}</span>}
        </button>
        <Dot codes={props.problems[String(record.id)]} />
        {record.children > 0 && <span className="text-xs text-slate-400">{record.children}</span>}
      </div>
      {open && (
        <ul className="ml-3 border-l border-slate-200 pl-2">
          <Groups props={props} parent={record} />
        </ul>
      )}
    </li>
  );
}

function RootItem({ props, kindId, placedElsewhere }: { props: TreeProps; kindId: Id; placedElsewhere: boolean }) {
  const node = rootNode(kindId);
  const open = props.expanded.has(node);
  const kind = props.schema.kinds.find((k) => k.id === kindId);
  // How many sit at the top: every record of a root kind, the unplaced ones of another.
  const top = useChildren(props.domainId, `root:${kindId}`, null, { limit: 1 });
  const count = top.data?.total ?? 0;
  if (placedElsewhere && count === 0) return null;
  const chosen = props.selected?.kind === "root" && props.selected.kindId === kindId;
  return (
    <li>
      <div className={`${ROW} ${chosen ? "bg-blue-100 text-blue-900" : "hover:bg-slate-100"}`}>
        <Toggle open={open} count={count} label={kind?.name ?? ""} onClick={() => props.toggle(node)} />
        <button type="button" className="flex-1 text-left font-semibold" onClick={() => props.onSelect({ kind: "root", kindId })}>
          {kind?.name}
          <span className="ml-1 font-normal text-slate-500">
            ({count}
            {placedElsewhere ? " not placed" : ""})
          </span>
        </button>
      </div>
      {open && (
        <ul className="ml-3 border-l border-slate-200 pl-2">
          <Records props={props} group={`root:${kindId}`} parent={null} />
        </ul>
      )}
    </li>
  );
}

/**
 * The domain's records as one tree, read from the model: each root kind at the top, and under each
 * record the records that name it (a depot under its region, a truck under its depot). Branches load
 * as they open. Records of other kinds that are placed under nothing are listed last, so nothing is
 * out of reach. A record dragged onto another is placed under it, when its kind can be.
 */
export default function WorkbenchTree(props: TreeProps) {
  const { schema } = props;
  const others = schema.kinds.filter((k) => !k.is_abstract && !schema.roots.includes(k.id));
  return (
    <nav aria-label="Records tree">
      <ul className="space-y-0.5">
        {schema.roots.map((k) => (
          <RootItem key={k} props={props} kindId={k} placedElsewhere={false} />
        ))}
      </ul>
      {others.length > 0 && (
        <ul className="mt-3 space-y-0.5 border-t border-slate-200 pt-2" aria-label="Not placed under anything">
          {others.map((k) => (
            <RootItem key={k.id} props={props} kindId={k.id} placedElsewhere />
          ))}
        </ul>
      )}
    </nav>
  );
}


