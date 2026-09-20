import { isExpressionGroup, type ExpressionDocument, type ExpressionGroup, type ExpressionRule } from "./document";
import { EXPRESSION_FUNCTIONS } from "./functions";
import type { EntityColumnName, ExpressionField, FieldCatalogue, RelationshipDirection } from "./fields";

/**
 * Evaluating a document against one entity, client-side.
 *
 * The semantics are SQL's, on purpose, because Task 14d compiles the SAME
 * document to SQL and the two must agree:
 *
 * - an absent value compares to nothing. `x > 5` and `x <= 5` are BOTH
 *   false when `x` is missing, exactly as a NULL would be in a WHERE
 *   clause. Only `is empty` / `is not empty` test for absence.
 * - a rule about `unit.capacity` is false for an entity that is not a
 *   unit -- whatever the operator. An attribute rule carries its entity
 *   type with it, which is how Task 14d compiles it too
 *   (`entity_type_id = :t AND <attrs predicate>`). This is deliberately
 *   NOT the same as "the value is absent": the first browser run had
 *   `unit.note is empty` matching every SHIFT as well, because a shift has
 *   no `unit.note` either, and that is not what anybody means. A
 *   relationship count belongs to no one type, so it is never narrowed
 *   this way. (The consequence is real: `and`-ing two entity types'
 *   attributes matches nothing. The validator warns about that rather than
 *   pretending otherwise.)
 * - `=` on text is case sensitive, as SQL's `=` is; `contains`,
 *   `starts with` and `ends with` are case INsensitive, as `ILIKE` is, and
 *   their argument is literal text -- `%` is a character here, so 14d must
 *   escape it rather than pass it through.
 *
 * Callers validate first. If one does not, an unresolvable rule is false
 * rather than true: an expression that visibly matches nothing is a better
 * failure than one that silently stops filtering.
 */

export type EntityColumns = Partial<Record<EntityColumnName, unknown>>;

export type EvaluationTarget = {
  /** The entity's `entity_type_id`, as the string the catalogue uses. */
  entityTypeId: string;
  columns: EntityColumns;
  attrs: Record<string, unknown>;
  /** Relationship counts by `degreeKey`. A missing key is zero -- no
   * relationships is a count of nought, not an absent value. */
  degrees: ReadonlyMap<string, number>;
};

export function degreeKey(relationshipTypeId: string, direction: RelationshipDirection): string {
  return `${relationshipTypeId}:${direction}`;
}

const ABSENT = Symbol("absent");
type Value = unknown | typeof ABSENT;

/** The entity type a field's value belongs to, or null for one every
 * entity has (a column, a relationship count). */
function ownerEntityTypeId(field: ExpressionField): string | null {
  const ref = field.ref.kind === "function" ? field.ref.argument : field.ref;
  return ref.kind === "attribute" ? ref.entityTypeId : null;
}

/** Whether the rule is about this entity at all. */
function fieldApplies(field: ExpressionField, target: EvaluationTarget): boolean {
  const owner = ownerEntityTypeId(field);
  return owner === null || owner === target.entityTypeId;
}

function baseValue(field: ExpressionField, target: EvaluationTarget): Value {
  const ref = field.ref.kind === "function" ? field.ref.argument : field.ref;
  if (ref.kind === "column") {
    const value = target.columns[ref.column];
    return value === undefined || value === null ? ABSENT : value;
  }
  if (ref.kind === "attribute") {
    const value = target.attrs[ref.attribute];
    return value === undefined || value === null ? ABSENT : value;
  }
  return target.degrees.get(degreeKey(ref.relationshipTypeId, ref.direction)) ?? 0;
}

/** Minutes-and-seconds since midnight, so "09:30" and "09:30:00" compare
 * equal instead of by string length. */
function timeSeconds(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$/.exec(value);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3] ?? 0);
}

function applyFunction(fn: string, value: unknown): Value {
  const date = () => (typeof value === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null);
  switch (fn) {
    case "year":
    case "month":
    case "day": {
      const match = date();
      if (!match) return ABSENT;
      return Number(match[{ year: 1, month: 2, day: 3 }[fn] as 1 | 2 | 3]);
    }
    case "hour":
    case "minute": {
      if (typeof value !== "string") return ABSENT;
      const seconds = timeSeconds(value);
      if (seconds === null) return ABSENT;
      return fn === "hour" ? Math.floor(seconds / 3600) : Math.floor((seconds % 3600) / 60);
    }
    case "lower":
      return typeof value === "string" ? value.toLowerCase() : ABSENT;
    case "upper":
      return typeof value === "string" ? value.toUpperCase() : ABSENT;
    case "length":
      return typeof value === "string" ? value.length : ABSENT;
    case "abs":
      return typeof value === "number" ? Math.abs(value) : ABSENT;
    case "count":
      // Already computed by `baseValue` from `degrees`.
      return value;
    default:
      return ABSENT;
  }
}

function fieldValue(field: ExpressionField, target: EvaluationTarget): Value {
  const base = baseValue(field, target);
  if (field.ref.kind !== "function") return base;
  if (base === ABSENT) return ABSENT;
  if (!EXPRESSION_FUNCTIONS[field.ref.fn]) return ABSENT;
  return applyFunction(field.ref.fn, base);
}

/** `a` compared with `b` as the field's data type: negative, zero or
 * positive, or null when they are not comparable. */
function compare(field: ExpressionField, a: unknown, b: unknown): number | null {
  if (field.dataType === "date") {
    // ISO dates are zero-padded, so a string compare IS chronological --
    // but only for well-formed ones, which is what the validator ensures.
    if (typeof a !== "string" || typeof b !== "string") return null;
    return a < b ? -1 : a > b ? 1 : 0;
  }
  if (field.dataType === "time") {
    if (typeof a !== "string" || typeof b !== "string") return null;
    const left = timeSeconds(a);
    const right = timeSeconds(b);
    if (left === null || right === null) return null;
    return left - right;
  }
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "string" && typeof b === "string") return a < b ? -1 : a > b ? 1 : 0;
  return null;
}

const fold = (value: unknown) => (typeof value === "string" ? value.toLowerCase() : "");

function evaluateRule(rule: ExpressionRule, catalogue: FieldCatalogue, target: EvaluationTarget): boolean {
  const field = catalogue.get(rule.field);
  if (!field) return false;
  // Before anything else, including the null operators: this rule is not
  // about an entity of another type.
  if (!fieldApplies(field, target)) return false;

  const actual = fieldValue(field, target);
  if (rule.operator === "null") return actual === ABSENT;
  if (rule.operator === "notNull") return actual !== ABSENT;
  if (actual === ABSENT) return false;

  const expected = rule.value;
  // `=` and `!=` go through the same comparison the ordering operators use
  // wherever one exists, so `09:30` equals `09:30:00` -- the two spellings
  // of a time SQL would compare equal as well. Where there is no ordering
  // (boolean), it falls back to strict equality. On text this is still
  // case sensitive: `compare` orders strings, and only identical ones
  // order equal.
  const equal = (): boolean => {
    const order = compare(field, actual, expected);
    return order === null ? actual === expected : order === 0;
  };
  switch (rule.operator) {
    case "=":
      return equal();
    case "!=":
      return !equal();
    case "<":
    case "<=":
    case ">":
    case ">=": {
      const order = compare(field, actual, expected);
      if (order === null) return false;
      if (rule.operator === "<") return order < 0;
      if (rule.operator === "<=") return order <= 0;
      if (rule.operator === ">") return order > 0;
      return order >= 0;
    }
    case "contains":
      return fold(actual).includes(fold(expected));
    case "doesNotContain":
      return !fold(actual).includes(fold(expected));
    case "beginsWith":
      return fold(actual).startsWith(fold(expected));
    case "endsWith":
      return fold(actual).endsWith(fold(expected));
    case "in":
      return Array.isArray(expected) && expected.includes(actual);
    case "notIn":
      return Array.isArray(expected) && !expected.includes(actual);
    default:
      return false;
  }
}

function evaluateGroup(group: ExpressionGroup, catalogue: FieldCatalogue, target: EvaluationTarget): boolean {
  // An empty group is no constraint, not an impossible one.
  let result = true;
  if (group.rules.length > 0) {
    const results = group.rules.map((node) =>
      isExpressionGroup(node)
        ? evaluateGroup(node, catalogue, target)
        : evaluateRule(node, catalogue, target)
    );
    result = group.combinator === "or" ? results.some(Boolean) : results.every(Boolean);
  }
  return group.not ? !result : result;
}

export function evaluateExpression(
  document: ExpressionDocument,
  catalogue: FieldCatalogue,
  target: EvaluationTarget
): boolean {
  return evaluateGroup(document.query, catalogue, target);
}
