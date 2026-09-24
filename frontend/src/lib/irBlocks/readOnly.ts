/**
 * The optimization view's read-only Blocks style, on the editable
 * vocabulary: the same blocks, fixed in place. Blocks that stand for a part
 * of the model carry that part's node id from `buildModelView`, so clicking
 * one opens the same side panel the other styles open.
 */
import type { GraphResponse } from "../../types/graph";
import { MODEL_NODE_PREFIX, OBJECTIVE_NODE_ID } from "../modelGraph";
import { partOfBlock } from "./catalogue";
import { irToBlocks, type IrLoc, type Workspace } from "./toBlocks";

/** Goal terms after the first carry this, so selecting any of them selects the goal. */
const LATER_TERM = `${OBJECTIVE_NODE_ID}-term-`;

export function readOnlyWorkspace(ir: Record<string, unknown> | null | undefined, graph: GraphResponse, title = ""): Workspace {
  const model = (ir ?? {}) as { sets?: string[]; constraints?: { id?: string }[] };
  const setIds = new Map(graph.nodes.filter((node) => node.type === "sets").map((node) => [node.label.split("\n")[0], node.id]));
  const ids = (loc: IrLoc): string | undefined => {
    const [key, at] = loc;
    if (key === "sets" && loc.length === 2) {
      const name = model.sets?.[at as number] ?? "";
      return setIds.get(name) ?? `${MODEL_NODE_PREFIX}set-${name}`;
    }
    if (key === "variables" && loc.length === 2) return `${MODEL_NODE_PREFIX}var-${String(at)}`;
    if (key === "parameters" && loc.length === 2) return `${MODEL_NODE_PREFIX}par-${String(at)}`;
    if (key === "constraints" && loc.length === 2) return `${MODEL_NODE_PREFIX}con-${model.constraints?.[at as number]?.id ?? at}`;
    if (key === "objective" && at === "terms" && loc.length === 3) return loc[2] === 0 ? OBJECTIVE_NODE_ID : `${LATER_TERM}${String(loc[2])}`;
    return undefined;
  };
  return irToBlocks(ir, { editable: false, title, ids });
}

/** The model part a clicked block belongs to: itself or the nearest part around it -- and, for anything inside a goal term, the goal. */
export function partFor(id: string | null, parentOf: (id: string) => string | null, known: Set<string>): string | null {
  const part = partOfBlock(id, parentOf, known);
  if (part) return part;
  // Later goal terms carry an id of their own that is no model part: walk up to one.
  for (let current = id; current; current = parentOf(current)) {
    if (current.startsWith(LATER_TERM)) return known.has(OBJECTIVE_NODE_ID) ? OBJECTIVE_NODE_ID : null;
  }
  return null;
}
