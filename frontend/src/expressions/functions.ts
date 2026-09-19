import type { AttrType } from "../api/v1";

/**
 * The function catalogue: a closed table of typed calls an expression may
 * contain.
 *
 * **This table is shared with Task 14d, which compiles the same document
 * to parameterised SQL.** So the rule for adding an entry is not "is it
 * useful on the client" but "can the server express it, safely, over
 * `entity.attrs`". Each entry therefore carries the SQL it becomes, in
 * `sql`, as documentation that travels with the definition rather than in
 * a comment somewhere else -- a function that existed here and not there
 * would be a promise the product could not keep.
 *
 * `{arg}` is the already-cast argument expression: for an attribute,
 * `(attrs->>'<name>')::<type>`; for a column, the column. Task 14d binds
 * the name as a parameter and never interpolates user text.
 *
 * Deliberately NOT here, and why:
 *
 * - `now()` / `today()` -- the client's clock and the server's are not the
 *   same clock, and neither is the database's time zone. The same document
 *   would filter differently in the two places.
 * - `sum(...)` / `avg(...)` over related entities -- expressible in SQL,
 *   but the argument would have to name a field on the *other* side of a
 *   relationship, which is a second kind of field reference and a bigger
 *   design than this task.
 * - `round(x, n)`, `substr(s, a, b)` -- two-argument calls. Every entry
 *   here is unary, which is what keeps the field grammar one level deep.
 * - nested calls (`abs(year(d))`) -- rejected by the validator, see
 *   `fields.decodeFieldId`.
 * - `count` over a "collection": v1 has no collection-valued attribute
 *   (`attrs` values are scalars), so `count` is over RELATIONSHIPS only.
 */

export type FunctionArgumentKind = "field" | "relationship";

export type FunctionDef = {
  name: string;
  /** What the call takes: an ordinary field, or a relationship type and a
   * direction (which is what makes `count` structurally different). */
  argument: FunctionArgumentKind;
  /** The data types the argument may have. Empty for a relationship. */
  argumentTypes: readonly AttrType[];
  /** The call's own data type -- or `"argument"` when it follows its
   * argument's, which only `abs` does. */
  returns: AttrType | "argument";
  /** What the call reads as, in the builder and in a message. */
  description: string;
  /** The SQL Task 14d compiles this to. */
  sql: string;
};

const DATE_PART = (part: string) => `EXTRACT(${part} FROM {arg})::int`;
const TIME_PART = (part: string) => `EXTRACT(${part} FROM {arg})::int`;

export const EXPRESSION_FUNCTIONS: Record<string, FunctionDef> = {
  year: {
    name: "year",
    argument: "field",
    argumentTypes: ["date"],
    returns: "integer",
    description: "the year of a date",
    sql: DATE_PART("YEAR"),
  },
  month: {
    name: "month",
    argument: "field",
    argumentTypes: ["date"],
    returns: "integer",
    description: "the month of a date, 1-12",
    sql: DATE_PART("MONTH"),
  },
  day: {
    name: "day",
    argument: "field",
    argumentTypes: ["date"],
    returns: "integer",
    description: "the day of the month, 1-31",
    sql: DATE_PART("DAY"),
  },
  hour: {
    name: "hour",
    argument: "field",
    argumentTypes: ["time"],
    returns: "integer",
    description: "the hour of a time of day, 0-23",
    sql: TIME_PART("HOUR"),
  },
  minute: {
    name: "minute",
    argument: "field",
    argumentTypes: ["time"],
    returns: "integer",
    description: "the minute of a time of day, 0-59",
    sql: TIME_PART("MINUTE"),
  },
  lower: {
    name: "lower",
    argument: "field",
    argumentTypes: ["text"],
    returns: "text",
    description: "text in lower case",
    sql: "lower({arg})",
  },
  upper: {
    name: "upper",
    argument: "field",
    argumentTypes: ["text"],
    returns: "text",
    description: "text in upper case",
    sql: "upper({arg})",
  },
  length: {
    name: "length",
    argument: "field",
    argumentTypes: ["text"],
    returns: "integer",
    description: "how many characters a text has",
    sql: "length({arg})",
  },
  abs: {
    name: "abs",
    argument: "field",
    // An integer's absolute value is an integer and a number's is a
    // number; `returns: "argument"` is what keeps the value editor and
    // Task 14d's cast in step with that.
    argumentTypes: ["integer", "number"],
    returns: "argument",
    description: "a number without its sign",
    sql: "abs({arg})",
  },
  count: {
    name: "count",
    argument: "relationship",
    argumentTypes: [],
    returns: "integer",
    description: "how many relationships of one type an entity has",
    // The one entry whose SQL is a correlated subquery rather than a
    // scalar expression. The direction chooses between three fixed
    // predicates -- it is never concatenated from user input.
    sql:
      "(SELECT count(*) FROM relationship r WHERE r.relationship_type_id = :relationship_type_id " +
      "AND {direction})  -- direction: outgoing => r.from_entity_id = entity.id | " +
      "incoming => r.to_entity_id = entity.id | any => (r.from_entity_id = entity.id OR r.to_entity_id = entity.id)",
  },
};

export const FUNCTION_NAMES: readonly string[] = Object.keys(EXPRESSION_FUNCTIONS);

/** A call's data type. `argumentType` is null for `count`, which has no
 * field argument. */
export function functionReturnType(def: FunctionDef, argumentType: AttrType | null): AttrType {
  if (def.returns !== "argument") return def.returns;
  // Only reachable for `abs`, whose argument types are both numeric.
  return argumentType ?? "number";
}
