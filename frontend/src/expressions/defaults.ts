import {
  EXPRESSION_VERSION,
  isExpressionGroup,
  type ExpressionDocument,
  type ExpressionGroup,
  type ExpressionRule,
} from "./document";
import { COLUMN_GROUP, encodeFieldId, type ExpressionField, type FieldCatalogue } from "./fields";
import { EXPRESSION_OPERATORS, operatorsForField } from "./operators";

/**
 * The rule "+ Condition" creates, and why nothing is filtered by it.
 *
 * Pressing "+ Condition" has to produce a rule the builder can render, so
 * it gets a field, an operator and a value. That rule is then structurally
 * valid, and until this module existed it was **sent immediately**: the
 * entity list went from 5 rows to 0 and the graph from 23 nodes to 2 the
 * moment the button was pressed, before the person had typed anything.
 * `Entities.tsx` documents the opposite intent -- "a half-written
 * condition must not blank the table" -- and an untouched condition is the
 * emptiest half there is.
 *
 * The fix is `isUntouchedRule`, and the shape of it is the point: a rule
 * is held back exactly while it is still **identical to the one the button
 * created**. Not a "pristine" flag, not a set of rule ids -- react-
 * querybuilder regenerates ids on every mount (`document.ts` says so and
 * strips them), so identity is not something this format can carry. Value
 * comparison needs no bookkeeping, survives a remount, and answers the
 * question the user would ask: have I changed anything about this
 * condition yet?
 *
 * The consequence to be aware of: a person who edits a rule back to
 * exactly the default has an untouched rule again, and it stops filtering.
 * With the default below that is the right answer anyway -- `key contains
 * ""` matches every row.
 */

const KEY_FIELD_ID = encodeFieldId({ kind: "column", column: "key" });

/**
 * The field a new rule starts on.
 *
 * It used to be `catalogue.fields[0]`, which is alphabetically first by
 * group then label -- and since a call sorts under its own name, that was
 * `abs(hourly_rate)`: a function over an attribute of whichever entity
 * type happened to sort first. A person who wanted a condition on
 * something was shown a wrapped numeric attribute they had not chosen and
 * probably did not know existed.
 *
 * So: the first PLAIN field (never a call), preferring the entity's own
 * columns -- `key` on the entity list, which is the one field every entity
 * has and the one people address entities by. The graph's catalogue
 * carries no columns at all (`graphFilter.ts` explains why), so there it
 * is the first plain attribute instead. A catalogue of nothing but calls
 * still gets a field rather than nothing.
 */
export function defaultFieldId(catalogue: FieldCatalogue): string | undefined {
  const plain = catalogue.fields.filter((field) => field.ref.kind !== "function");
  return (
    // `key` by name, not "the first column": the columns are sorted by
    // label too, so "first" is `active` -- a boolean whose default value is
    // `true`, i.e. a new condition that silently means "hide the inactive
    // ones". `key` is the only field every entity has and the one people
    // address entities by, and an empty `key` condition means nothing at
    // all, which is exactly what an untouched condition should mean.
    plain.find((field) => field.group === COLUMN_GROUP && field.id === KEY_FIELD_ID)?.id ??
    plain.find((field) => field.group === COLUMN_GROUP)?.id ??
    plain[0]?.id ??
    catalogue.fields[0]?.id
  );
}

/** The operator a rule on `field` starts with: the first its data type
 * offers. Shared with the builder so "what a new rule is" has one
 * definition. */
export function defaultOperatorFor(field: ExpressionField | undefined): string {
  return field ? operatorsForField(field)[0].name : "=";
}

/**
 * The value a NEW rule starts with, so that adding one does not produce an
 * error the user has to clear before they can do anything.
 *
 * Exported for its own test: the `list` branch is not reachable through
 * the UI today, because no data type's FIRST operator is a list one -- and
 * a mutant that returned a bare value there survived the whole suite.
 * Reordering `OPERATORS_BY_TYPE.enum` would reach it, so it is pinned here
 * rather than left to be discovered then.
 */
export function defaultValueFor(field: ExpressionField | undefined, operator: string): unknown {
  const arity = EXPRESSION_OPERATORS[operator]?.arity;
  if (arity === "unary") return null;
  if (!field) return "";
  const single = (): unknown => {
    switch (field.dataType) {
      case "integer":
      case "number":
        return 0;
      case "boolean":
        return true;
      case "enum":
        return field.enumValues?.[0] ?? "";
      case "date":
        return new Date().toISOString().slice(0, 10);
      case "time":
        return "00:00";
      default:
        return "";
    }
  };
  const value = single();
  return arity === "list" ? [value] : value;
}

/** The exact rule "+ Condition" produces against this catalogue, or null
 * when the catalogue offers nothing to build one from. */
export function defaultRule(catalogue: FieldCatalogue): ExpressionRule | null {
  const id = defaultFieldId(catalogue);
  if (id === undefined) return null;
  const field = catalogue.get(id);
  const operator = defaultOperatorFor(field);
  return { field: id, operator, value: defaultValueFor(field, operator) };
}

function sameValue(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, index) => sameValue(item, b[index]))
    );
  }
  return a === b;
}

/** True while the person has not changed any of a new rule's three
 * controls. A `date` default is today, so this is evaluated against a
 * freshly built default rather than a cached one. */
export function isUntouchedRule(rule: ExpressionRule, catalogue: FieldCatalogue): boolean {
  const fresh = defaultRule(catalogue);
  if (!fresh) return false;
  return (
    rule.field === fresh.field &&
    rule.operator === fresh.operator &&
    sameValue(rule.value, fresh.value)
  );
}

function pruneGroup(group: ExpressionGroup, catalogue: FieldCatalogue): ExpressionGroup {
  const rules = group.rules
    .map((node) => (isExpressionGroup(node) ? pruneGroup(node, catalogue) : node))
    .filter((node) => isExpressionGroup(node) || !isUntouchedRule(node, catalogue));
  return group.not ? { combinator: group.combinator, not: true, rules } : { combinator: group.combinator, rules };
}

/**
 * The document with every still-untouched rule removed -- what is worth
 * sending, as opposed to what the builder shows.
 *
 * Both are needed and they are not the same: the builder must keep
 * rendering the new rule (it is the row the person is about to fill in),
 * while the filter must ignore it. Groups are kept even when pruning
 * empties them, because `isEmptyDocument` already reads an empty group as
 * "no constraint" and rebuilding the group structure here would change
 * what a later, touched rule is combined with.
 */
export function withoutUntouchedRules(
  document: ExpressionDocument | null,
  catalogue: FieldCatalogue
): ExpressionDocument | null {
  if (!document) return null;
  return { version: EXPRESSION_VERSION, query: pruneGroup(document.query, catalogue) };
}
