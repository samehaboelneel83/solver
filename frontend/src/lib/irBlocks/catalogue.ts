/**
 * What an editable block may offer. A dropdown is only ever filled from
 * here and from the block's own surroundings, so it offers admissible
 * choices -- the rule the forms' `ReferencePicker` applies -- and always
 * keeps the value it already holds, even one the domain no longer has, so a
 * loaded model shows what it says and round-trips exactly.
 */
import type * as Blockly from "blockly";

export const NONE = "";

export type BlockCatalogue = {
  entityTypes: { name: string; attributes: { name: string; data_type: string }[] }[];
  parameters: { name: string; index: string[] }[];
  relationships: { name: string; from: string; to: string }[];
};
export const EMPTY_CATALOGUE: BlockCatalogue = { entityTypes: [], parameters: [], relationships: [] };

const catalogues = new WeakMap<Blockly.Workspace, BlockCatalogue>();
export function setCatalogue(workspace: Blockly.Workspace, catalogue: BlockCatalogue): void {
  catalogues.set(workspace, catalogue);
}
export function catalogueOf(workspace: Blockly.Workspace | null | undefined): BlockCatalogue {
  return (workspace && catalogues.get(workspace)) || EMPTY_CATALOGUE;
}

/** Blockly options for `values`, keeping `current` first-class even when it is no longer offered. */
export function menu(values: string[], current: string | null | undefined, label: (value: string) => string = (v) => v || "(choose)"): [string, string][] {
  const all = [...values];
  if (current !== null && current !== undefined && !all.includes(current)) all.unshift(current);
  if (all.length === 0) all.push(NONE);
  return all.map((value) => [label(value), value]);
}

/** index -> set for each binding in the stack starting at `first`. */
export function bindingsOf(first: Blockly.Block | null): [string, string][] {
  const out: [string, string][] = [];
  for (let b = first; b; b = b.getNextBlock()) {
    if (b.type === "ir_binding") out.push([b.getFieldValue("INDEX"), b.getFieldValue("SET")]);
  }
  return out;
}

/** The statement input of `parent` that `child` sits in (directly or down its stack). */
function inputHolding(parent: Blockly.Block, child: Blockly.Block): string | null {
  for (const input of parent.inputList) {
    let b = input.connection?.targetBlock() ?? null;
    while (b) {
      if (b === child) return input.name;
      b = b.getNextBlock();
    }
  }
  return null;
}

/**
 * index -> set for every index bound around `block`: the enclosing rule's
 * FORALL (and a cumulative's OVER, for its demand), enclosing sums' OVER when
 * the block is in the sum's BODY, and -- for a binding -- the bindings
 * before it in its own stack (a `via` anchors on an earlier index, never on
 * itself). Outer scopes first, so a Map keeps the reading order.
 */
export function scopeAt(block: Blockly.Block): Map<string, string> {
  const layers: [string, string][][] = [];
  if (block.type === "ir_binding") {
    // The bindings above this one in its own stack. `getPreviousBlock()` of
    // the first binding is the block that holds the stack (a rule, a sum),
    // which is not a binding, so the walk stops there.
    const before: [string, string][] = [];
    let came: Blockly.Block = block;
    for (let b = block.getPreviousBlock(); b && b.type === "ir_binding" && b.getNextBlock() === came; came = b, b = b.getPreviousBlock()) {
      before.unshift([b.getFieldValue("INDEX"), b.getFieldValue("SET")]);
    }
    layers.push(before);
  }
  let child: Blockly.Block = block;
  for (let parent = block.getSurroundParent(); parent; child = parent, parent = parent.getSurroundParent()) {
    const holding = inputHolding(parent, child) ?? parent.getInputWithBlock(child)?.name ?? null;
    if (parent.type === "ir_sum" && holding === "BODY") layers.unshift(bindingsOf(parent.getInputTargetBlock("OVER")));
    if (parent.type === "ir_sum" && holding === "OVER") continue;
    if (["ir_rule", "ir_no_overlap", "ir_cumulative"].includes(parent.type) && holding !== "FORALL") {
      // A cumulative's demand is per interval, so it sees the OVER indices;
      // its capacity is one number for them all, so it does not.
      if (parent.type === "ir_cumulative" && holding === "DEMAND") layers.unshift(bindingsOf(parent.getInputTargetBlock("OVER")));
      layers.unshift(bindingsOf(parent.getInputTargetBlock("FORALL")));
    }
  }
  const scope = new Map<string, string>();
  for (const layer of layers) for (const [index, set] of layer) if (index && !scope.has(index)) scope.set(index, set);
  return scope;
}

export function declared(workspace: Blockly.Workspace) {
  const variables = new Map<string, { index: string[]; domain: string }>();
  const parameters = new Map<string, { index: string[] }>();
  const sets: string[] = [];
  const root = workspace.getBlockById("model-root");
  for (let b = root?.getInputTargetBlock("DECLARE") ?? null; b; b = b.getNextBlock()) {
    if (b.type === "ir_set") sets.push(b.getFieldValue("SET"));
    if (b.type === "ir_variable") {
      const arity = Number(b.getFieldValue("ARITY"));
      variables.set(b.getFieldValue("NAME"), {
        index: Array.from({ length: arity }, (_, i) => b.getFieldValue(`SET${i}`)),
        domain: b.getFieldValue("DOMAIN"),
      });
    }
    if (b.type === "ir_parameter") parameters.set(b.getFieldValue("NAME"), { index: (b as unknown as { index: string[] }).index ?? [] });
  }
  return { variables, parameters, sets };
}

export function partOfBlock(id: string | null, parentOf: (id: string) => string | null, known: Set<string>): string | null {
  let current = id;
  while (current) {
    if (known.has(current)) return current;
    current = parentOf(current);
  }
  return null;
}

/** The catalogue from what the domain's API lists: entity types with their
 * attributes, parameter defs (index as type ids) and relationship types. */
export function catalogueFrom(
  entityTypes: readonly { id: number | string; name: string; attributes?: readonly { name: string; data_type: string }[] }[],
  parameterDefs: readonly { name: string; index_type_ids: readonly (number | string)[] }[],
  relationshipTypes: readonly { name: string; from_type_id: number | string; to_type_id: number | string }[]
): BlockCatalogue {
  const nameOf = (id: number | string) => entityTypes.find((t) => String(t.id) === String(id))?.name ?? `#${id}`;
  return {
    entityTypes: entityTypes.map((t) => ({ name: t.name, attributes: (t.attributes ?? []).map((a) => ({ name: a.name, data_type: a.data_type })) })),
    parameters: parameterDefs.map((p) => ({ name: p.name, index: p.index_type_ids.map(nameOf) })),
    relationships: relationshipTypes.map((r) => ({ name: r.name, from: nameOf(r.from_type_id), to: nameOf(r.to_type_id) })),
  };
}
