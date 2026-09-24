import type { AttrType } from "../api/v1";
import type { ExpressionField } from "./fields";

/**
 * The operator table: which comparisons each v1 data type offers, and what
 * shape of value each comparison takes.
 *
 * Data, deliberately -- not a `switch` in the builder and another one in
 * the evaluator and a third in Task 14d. "is greater than" on a boolean
 * and "starts with" on an integer are not merely useless, they are
 * meaningless in the SQL the server will generate.
 *
 * The names are react-querybuilder's own (`=`, `beginsWith`, `notNull`,
 * ...), so the library's defaults still line up with them and a document
 * written by hand against its documentation is readable here. The LABELS
 * are ours, in words: `<=` beside a date reads as nothing at all.
 */

export type OperatorArity =
  /** Takes one value of the field's data type. */
  | "binary"
  /** Takes no value at all. */
  | "unary"
  /** Takes a non-empty list of values of the field's data type. */
  | "list";

export type OperatorDef = { name: string; label: string; arity: OperatorArity };

function def(name: string, label: string, arity: OperatorArity = "binary"): OperatorDef {
  return { name, label, arity };
}

export const EXPRESSION_OPERATORS: Record<string, OperatorDef> = {
  "=": def("=", "is"),
  "!=": def("!=", "is not"),
  "<": def("<", "is less than"),
  "<=": def("<=", "is at most"),
  ">": def(">", "is greater than"),
  ">=": def(">=", "is at least"),
  contains: def("contains", "contains"),
  doesNotContain: def("doesNotContain", "does not contain"),
  beginsWith: def("beginsWith", "starts with"),
  endsWith: def("endsWith", "ends with"),
  in: def("in", "is one of", "list"),
  notIn: def("notIn", "is not one of", "list"),
  null: def("null", "is empty", "unary"),
  notNull: def("notNull", "is not empty", "unary"),
};

const ORDERED = ["=", "!=", "<", "<=", ">", ">="] as const;

/**
 * The operators each data type offers, before the null pair is added.
 *
 * `between` is not here on purpose: it would make a rule's value a
 * two-element tuple, and everything else in this format is one scalar or a
 * list of scalars. `x >= a AND x <= b` says the same thing with two rules.
 */
export const OPERATORS_BY_TYPE: Record<AttrType, readonly string[]> = {
  integer: [...ORDERED],
  number: [...ORDERED],
  date: [...ORDERED],
  time: [...ORDERED],
  text: ["=", "!=", "contains", "doesNotContain", "beginsWith", "endsWith"],
  boolean: ["=", "!="],
  enum: ["=", "!=", "in", "notIn"],
  // A shape is not compared; it is drawn (GeometryPreview) and read by the
  // spatial operations, never filtered on.
  geometry: [],
};

/** Offered on any field that can be absent. */
export const NULL_OPERATORS: readonly string[] = ["null", "notNull"];

/**
 * Where a data type reads better in its own words than in the shared
 * numeric ones.
 *
 * A date IS ordered, so it offers the same four comparisons an integer
 * does and compiles to the same SQL -- but nobody says one date is *less
 * than* another, and "hired_on is less than 2024-01-01" was the one place
 * an otherwise carefully type-aware builder (enum → "is one of" and a
 * dropdown, date → a native date picker) made the reader translate. Only
 * the LABEL changes; the operator NAME on the wire is untouched, because
 * that is what the server compiles.
 *
 * Numbers deliberately keep the numeric wording: "hourly_rate is before
 * 20" would be this same bug with the types swapped.
 */
const LABEL_BY_TYPE: Partial<Record<AttrType, Record<string, string>>> = {
  date: {
    "<": "is before",
    "<=": "is on or before",
    ">": "is after",
    ">=": "is on or after",
  },
  time: {
    "<": "is before",
    "<=": "is at or before",
    ">": "is after",
    ">=": "is at or after",
  },
};

/** The operators a particular field offers: its data type's, plus the null
 * pair when the field can be absent. A required attribute is guaranteed
 * present by `entity_validate`, so "is empty" there would be dead UI. */
export function operatorsForField(field: ExpressionField): OperatorDef[] {
  const names = [
    ...OPERATORS_BY_TYPE[field.dataType],
    ...(field.nullable ? NULL_OPERATORS : []),
  ];
  const overrides = LABEL_BY_TYPE[field.dataType];
  return names.map((name) => {
    const def = EXPRESSION_OPERATORS[name];
    const label = overrides?.[name];
    return label ? { ...def, label } : def;
  });
}

/** Whether `operator` is one `field` offers. */
export function fieldAllowsOperator(field: ExpressionField, operator: string): boolean {
  return operatorsForField(field).some((o) => o.name === operator);
}
