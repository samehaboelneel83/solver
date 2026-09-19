import type { RuleGroupType, RuleType } from "react-querybuilder";
import { EXPRESSION_OPERATORS } from "./operators";

/**
 * The expression document: the one serialisable shape every consumer
 * stores, and the one Task 14d receives over the wire and compiles to
 * parameterised SQL.
 *
 * It is react-querybuilder's own `RuleGroupType`, narrowed -- not a second
 * format beside it. Two things are narrowed away:
 *
 * - `id` and `path`, which the library regenerates on every mount. Keeping
 *   them would make two identical expressions compare unequal and would
 *   send per-session noise to the server.
 * - `valueSource: "field"` (comparing one field to another) and the
 *   independent-combinator variant (`RuleGroupTypeIC`). Both are real
 *   react-querybuilder features; neither is expressed in version 1, so
 *   neither can arrive at 14d's compiler as a surprise.
 *
 * `version` is here from the first document ever written, so that server
 * can refuse what it does not understand instead of mis-reading it.
 */

export const EXPRESSION_VERSION = 1;

export type ExpressionCombinator = "and" | "or";

export type ExpressionRule = {
  field: string;
  operator: string;
  /** Kept at its JSON type: an integer field's value is a number, a
   * boolean's is a boolean, a list operator's is an array. A value whose
   * type disagrees with its field makes the document invalid -- see
   * `validate.ts`, which is where that judgement lives. */
  value: unknown;
};

export type ExpressionGroup = {
  combinator: ExpressionCombinator;
  not?: boolean;
  rules: (ExpressionRule | ExpressionGroup)[];
};

export type ExpressionDocument = {
  version: typeof EXPRESSION_VERSION;
  query: ExpressionGroup;
};

export function isExpressionGroup(node: ExpressionRule | ExpressionGroup): node is ExpressionGroup {
  return Array.isArray((node as ExpressionGroup).rules);
}

export function emptyDocument(): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: { combinator: "and", rules: [] } };
}

function normaliseRule(rule: RuleType): ExpressionRule {
  const arity = EXPRESSION_OPERATORS[rule.operator]?.arity;
  return {
    field: rule.field,
    operator: rule.operator,
    // "is empty" has no value, but the builder leaves the previous
    // operator's behind. Dropping it here means one expression has one
    // serialisation, whatever route the user took to it.
    value: arity === "unary" ? null : (rule.value as unknown),
  };
}

function normaliseGroup(group: RuleGroupType): ExpressionGroup {
  const out: ExpressionGroup = {
    combinator: group.combinator === "or" ? "or" : "and",
    rules: (group.rules ?? []).map((node) =>
      Array.isArray((node as RuleGroupType).rules)
        ? normaliseGroup(node as RuleGroupType)
        : normaliseRule(node as RuleType)
    ),
  };
  if (group.not) out.not = true;
  return out;
}

/** A builder query as the document that is stored and sent. */
export function toDocument(query: RuleGroupType): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: normaliseGroup(query) };
}

/** A document as a query the builder can render. The narrowed shape is
 * already a valid `RuleGroupType`; the library fills in the ids. */
export function toQuery(document: ExpressionDocument | null): RuleGroupType {
  return (document?.query ?? emptyDocument().query) as RuleGroupType;
}

function walk(group: ExpressionGroup, onRule: (rule: ExpressionRule) => void): void {
  for (const node of group.rules) {
    if (isExpressionGroup(node)) walk(node, onRule);
    else onRule(node);
  }
}

/** How many rules the document holds, at any depth. What the collapsed
 * filter button counts. */
export function countRules(document: ExpressionDocument | null): number {
  if (!document) return 0;
  let n = 0;
  walk(document.query, () => {
    n += 1;
  });
  return n;
}

/** True when there is nothing to filter by: no document, or a document
 * whose groups are all empty. An empty document filters nothing. */
export function isEmptyDocument(document: ExpressionDocument | null): boolean {
  return countRules(document) === 0;
}
