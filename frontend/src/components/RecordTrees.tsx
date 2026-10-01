import { useState } from "react";
import { Link } from "react-router-dom";
import { formatApiError } from "../api/errors";
import { useEntityTrees, type EntityTree, type Id, type TreeNode } from "../api/v1";

const LINK = "rounded text-blue-600 underline";

function name(n: Pick<TreeNode, "key" | "label">) {
  return n.label ? `${n.label} (${n.key})` : n.key;
}

/** Children grouped under their parent, for nesting. */
function byParent(nodes: TreeNode[]): Map<Id, TreeNode[]> {
  const out = new Map<Id, TreeNode[]>();
  for (const n of nodes) {
    if (n.parent_id == null) continue;
    out.set(n.parent_id, [...(out.get(n.parent_id) ?? []), n]);
  }
  return out;
}

function Branch({ parent, kids, open }: { parent: Id; kids: Map<Id, TreeNode[]>; open: number }) {
  const children = kids.get(parent) ?? [];
  if (children.length === 0) return null;
  return (
    <ul className="ml-4 border-l border-slate-200 pl-3">
      {children.map((n) => (
        <Node key={n.id} node={n} kids={kids} open={open} />
      ))}
    </ul>
  );
}

function Node({ node, kids, open }: { node: TreeNode; kids: Map<Id, TreeNode[]>; open: number }) {
  const below = kids.get(node.id)?.length ?? 0;
  const [expanded, setExpanded] = useState(node.depth < open);
  return (
    <li className="py-0.5">
      {below > 0 ? (
        <button
          type="button"
          className="mr-1 w-4 text-slate-500"
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} the ${below} under ${node.key}`}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "▾" : "▸"}
        </button>
      ) : (
        <span className="mr-1 inline-block w-4" />
      )}
      <Link to={`/entities/${node.id}`} className={LINK}>
        {name(node)}
      </Link>
      {below > 0 && !expanded && <span className="ml-1 text-xs text-slate-500">+{below}</span>}
      {expanded && <Branch parent={node.id} kids={kids} open={open} />}
    </li>
  );
}

function Tree({ tree, self }: { tree: EntityTree; self: { id: Id; key: string; label: string | null } }) {
  const kids = byParent(tree.descendants);
  const how = tree.via_attribute
    ? `through the “${tree.via_attribute}” field`
    : tree.is_hierarchy
      ? "a hierarchy"
      : "a relationship between records of this kind";
  return (
    <div className="rounded-md border border-slate-200 p-3" data-testid={`tree-${tree.name}`}>
      <h3 className="text-sm font-semibold text-slate-900">
        {tree.name} <span className="font-normal text-slate-500">— {how}</span>
      </h3>
      {tree.loop && (
        <p role="alert" className="mt-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-800">
          This chain comes back on itself: following “{tree.name}” returns to a record already passed. Change one
          link to break the loop.
        </p>
      )}
      <nav aria-label={`Above in ${tree.name}`} className="mt-2 text-sm">
        {tree.ancestors.length === 0 ? (
          <span className="text-slate-500">Top of the tree — nothing above.</span>
        ) : (
          <ol className="flex flex-wrap items-center gap-1">
            {[...tree.ancestors].reverse().map((a) => (
              <li key={a.id} className="flex items-center gap-1">
                <Link to={`/entities/${a.id}`} className={LINK}>
                  {name(a)}
                </Link>
                <span aria-hidden="true" className="text-slate-400">
                  ›
                </span>
              </li>
            ))}
            <li className="font-medium" aria-current="page">
              {name(self)}
            </li>
          </ol>
        )}
      </nav>
      <div className="mt-2 text-sm">
        {tree.descendants.length === 0 ? (
          <p className="text-slate-500">Nothing below.</p>
        ) : (
          <>
            <p className="text-slate-600">
              {tree.descendants.length} below{tree.truncated ? " (the first ones; the tree is larger)" : ""}:
            </p>
            <Branch parent={self.id} kids={kids} open={1} />
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Where a record sits in every relationship that nests its kind inside itself: the chain above
 * it, the tree below it, and a warning when the chain loops. Nothing is shown for a kind that
 * nests in nothing.
 */
export default function RecordTrees({ entity }: { entity: { id: Id; key: string; label: string | null } }) {
  const trees = useEntityTrees(entity.id);
  if (trees.isError) {
    return <p className="text-sm text-red-700">Could not read this record's trees: {formatApiError(trees.error)}</p>;
  }
  const list = trees.data?.trees ?? [];
  if (list.length === 0) return null;
  return (
    <section aria-labelledby="record-trees" className="space-y-3 rounded-md border border-slate-200 bg-white p-4">
      <h2 id="record-trees" className="text-base font-semibold text-slate-900">
        Above and below
      </h2>
      {list.map((t) => (
        <Tree key={t.relationship_type_id} tree={t} self={entity} />
      ))}
    </section>
  );
}
