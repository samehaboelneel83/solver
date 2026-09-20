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
 * So a document can be perfectly valid *as a filter* and still be more than
 * a constraint binding can say. That must be refused with the reason, never
 * flattened: silently turning `a OR b` into `a AND b` would change which
 * entities a constraint ranges over, and the model would be wrong in a way
 * nothing downstream could detect.
 */

import type { ExpressionDocument, ExpressionGroup, ExpressionRule } from "../expressions";
import { FILTER_OPERATORS } from "../ir/contract";

/** One entry of an IR binding's `where`. */
export type IrFilter = { attr: string; op: string; value: unknown };

export type ToIrResult =
  | { ok: true; where: IrFilter[] }
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
  const where: IrFilter[] = [];
  const root = document.query;

  if (root.not) {
    problems.push("A binding filter cannot be negated here. Invert each condition instead.");
  }
  if (root.combinator === "or") {
    problems.push(
      "A binding filter joins its conditions with and. Use one condition per line, or widen the set."
    );
  }

  for (const node of root.rules ?? []) {
    if (isGroup(node)) {
      problems.push("A binding filter has no groups: every condition sits at the top level.");
      continue;
    }
    const name = attributeName(node.field);
    if (name === null) {
      problems.push(
        `${node.field} is not an attribute of this set. A binding filters on its own set's attributes.`
      );
      continue;
    }
    if (!FILTER_OPS.has(node.operator)) {
      problems.push(`${name}: ${node.operator} is not a comparison a binding filter offers.`);
      continue;
    }
    where.push({ attr: name, op: node.operator, value: node.value });
  }

  return problems.length > 0 ? { ok: false, problems } : { ok: true, where };
}

/**
 * The other direction, for editing a constraint that already exists. The
 * entity type id is needed because the catalogue identifies a field by it,
 * while the IR — whose binding already names the set — does not carry it.
 */
export function fromIrWhere(
  where: readonly IrFilter[] | undefined,
  entityTypeId: number | string
): ExpressionDocument {
  return {
    version: 1,
    query: {
      combinator: "and",
      rules: (where ?? []).map((filter) => ({
        field: `attr:${entityTypeId}:${filter.attr}`,
        operator: filter.op,
        value: filter.value,
      })) as ExpressionRule[],
    },
  } as ExpressionDocument;
}
