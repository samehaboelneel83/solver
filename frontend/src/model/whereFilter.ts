/**
 * The react-querybuilder document a person edits, and the `where` list the IR
 * contract admits, converted both ways.
 *
 * **These are not the same language, and the gap is the point of this file.**
 * The builder expresses a tree: nested groups, `or`, negation. The IR's
 * `where` is a flat AND-list of conditions over one binding's own set
 * (contract §4.1), deliberately — the full boolean tree already exists in the
 * expression core and can be lifted into the IR in v2 if a real model needs
 * it.
 *
 * Version 2 lets `where` hold "or" groups one level deep ({"any": [...]}),
 * so the builder's top level joins with and, and a group directly under it
 * joins with or. Anything else -- a group joined with and, a group in a
 * group, negation -- is still more than a binding can say.
 *
 * So a document can be perfectly valid *as a filter* and still be more than
 * a constraint binding can say. That must be refused with the reason, never
 * flattened: silently turning `a OR b` into `a AND b` would change which
 * entities a constraint ranges over, and the model would be wrong in a way
 * nothing downstream could detect.
 */

import type { ExpressionDocument, ExpressionGroup, ExpressionRule } from "../expressions";
import { FILTER_OPERATORS } from "../ir/contract";

/** One filter of an IR binding's `where`. */
export type IrFilter = { attr: string; op: string; value: unknown };
/** One entry of a `where`: a filter, or a group of filters any one of which is enough. */
export type IrWhereEntry = IrFilter | { any: IrFilter[] };

export type ToIrResult =
  | { ok: true; where: IrWhereEntry[] }
  | { ok: false; problems: string[] };

const FILTER_OPS: ReadonlySet<string> = new Set<string>(FILTER_OPERATORS);

function isGroup(node: ExpressionRule | ExpressionGroup): node is ExpressionGroup {
  return "rules" in node;
}

/**
 * `attr:<entityTypeId>:<name>` is how the expression catalogue identifies an
 * attribute field. A binding already knows its set, so the IR keeps only the
 * name.
 */
export function attributeName(fieldId: string): string | null {
  const parts = fieldId.split(":");
  return parts.length === 3 && parts[0] === "attr" ? parts[2] : null;
}

export function toIrWhere(document: ExpressionDocument | null): ToIrResult {
  if (!document) return { ok: true, where: [] };
  const problems: string[] = [];
  const where: IrWhereEntry[] = [];
  const root = document.query;

  if (root.not) {
    problems.push("A binding filter cannot be negated here. Invert each condition instead.");
  }
  if (root.combinator === "or") {
    problems.push(
      "A binding filter joins its conditions with and. For “this or that”, put them in a group."
    );
  }

  const filter = (node: ExpressionRule): IrFilter | null => {
    const name = attributeName(node.field);
    if (name === null) {
      problems.push(
        `${node.field} is not an attribute of this set. A binding filters on its own set's attributes.`
      );
      return null;
    }
    if (!FILTER_OPS.has(node.operator)) {
      problems.push(`${name}: ${node.operator} is not a comparison a binding filter offers.`);
      return null;
    }
    return { attr: name, op: node.operator, value: node.value };
  };

  for (const node of root.rules ?? []) {
    if (isGroup(node)) {
      if (node.not) problems.push("A group cannot be negated here. Invert each condition instead.");
      if (node.combinator !== "or") problems.push("Conditions in a group are joined with or.");
      if ((node.rules ?? []).some(isGroup)) problems.push("A group holds conditions, not other groups.");
      const any = (node.rules ?? []).filter((r): r is ExpressionRule => !isGroup(r)).map(filter);
      if (any.length < 2) problems.push("An “or” group needs two or more conditions.");
      if (any.every((f): f is IrFilter => f !== null)) where.push({ any });
      continue;
    }
    const one = filter(node);
    if (one) where.push(one);
  }

  return problems.length > 0 ? { ok: false, problems } : { ok: true, where };
}

/**
 * The other direction, for editing a constraint that already exists. The
 * entity type id is needed because the catalogue identifies a field by it,
 * while the IR — whose binding already names the set — does not carry it.
 */
export function fromIrWhere(
  where: readonly IrWhereEntry[] | undefined,
  entityTypeId: number | string
): ExpressionDocument {
  const rule = (filter: IrFilter) => ({
    field: `attr:${entityTypeId}:${filter.attr}`,
    operator: filter.op,
    value: filter.value,
  });
  return {
    version: 1,
    query: {
      combinator: "and",
      rules: (where ?? []).map((entry) =>
        "any" in entry ? { combinator: "or", rules: entry.any.map(rule) } : rule(entry)
      ) as ExpressionRule[],
    },
  } as ExpressionDocument;
}
