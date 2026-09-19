import { parseAttrValue } from "../components/attrTypes";
import type { AttrType } from "../api/v1";
import {
  EXPRESSION_VERSION,
  isExpressionGroup,
  type ExpressionDocument,
  type ExpressionGroup,
  type ExpressionRule,
} from "./document";
import { EXPRESSION_FUNCTIONS } from "./functions";
import { EXPRESSION_OPERATORS, fieldAllowsOperator } from "./operators";
import {
  decodeFieldId,
  encodeFieldId,
  type ExpressionField,
  type FieldCatalogue,
} from "./fields";

/**
 * Is this document one the catalogue can answer?
 *
 * The check lives here rather than in each consumer, because there will be
 * several: the graph filter (Task 14c), the entity list over HTTP (14d)
 * and, when the solver's IR is settled, the model editor. A consumer asks
 * `validateExpression(...).valid`; if it is true, `result.document` is the
 * document narrowed to `ExpressionDocument`, and evaluating or compiling
 * it will not meet a field, operator, function or value it cannot handle.
 *
 * Problems are separate from WARNINGS. A problem means the document cannot
 * be used. A warning means it can, and probably will not do what its
 * author meant -- `and`-ing attributes of two entity types, for instance,
 * which is correct, expressible, and always matches nothing, because an
 * entity has exactly one type.
 */

export type ExpressionProblemCode =
  | "unsupported_version"
  | "malformed"
  | "bad_combinator"
  | "too_deep"
  | "unknown_field"
  | "unknown_function"
  | "nested_function"
  | "bad_argument_type"
  | "bad_operator"
  | "bad_value_type"
  | "bad_enum_value"
  | "empty_list";

export type ExpressionProblem = {
  /** The rule's position: the indices from the root group down. `[]` is
   * the document as a whole. */
  path: number[];
  code: ExpressionProblemCode;
  message: string;
};

export type ExpressionWarning = { path: number[]; code: "mixed_entity_types"; message: string };

export type ValidationResult = {
  valid: boolean;
  problems: ExpressionProblem[];
  warnings: ExpressionWarning[];
  /** Only meaningful when `valid`. */
  document: ExpressionDocument;
};

/** How deeply groups may nest. A guard on what arrives from the wire, not
 * a limit anybody will reach by clicking: the evaluator and Task 14d's
 * compiler both recurse. */
export const MAX_DEPTH = 10;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// --- one rule ---------------------------------------------------------------

/** Why this field id is not in the catalogue -- as specifically as the id
 * itself allows. */
function fieldProblem(id: string, catalogue: FieldCatalogue): { code: ExpressionProblemCode; message: string } {
  const ref = decodeFieldId(id);
  if (!ref) {
    // The one shape worth naming on its own: `abs(year(d))` is a thing
    // somebody will try, and "unknown field" would be a lie about why.
    if (id.startsWith("fn:") && id.slice(3).includes("fn:")) {
      return { code: "nested_function", message: `One function inside another is not supported: "${id}".` };
    }
    return { code: "unknown_field", message: `"${id}" is not a field of this domain.` };
  }
  if (ref.kind === "function") {
    const def = EXPRESSION_FUNCTIONS[ref.fn];
    if (!def) {
      return { code: "unknown_function", message: `There is no function called "${ref.fn}".` };
    }
    if (ref.argument.kind === "relationship") {
      return {
        code: "unknown_field",
        message: `count() names a relationship type this domain does not have.`,
      };
    }
    const argument = catalogue.get(encodeFieldId(ref.argument));
    if (!argument) {
      return { code: "unknown_field", message: `${def.name}() names a field this domain does not have.` };
    }
    if (!def.argumentTypes.includes(argument.dataType)) {
      return {
        code: "bad_argument_type",
        message: `${def.name}() takes ${def.argumentTypes.join(" or ")}, and ${argument.label} is ${argument.dataType}.`,
      };
    }
    // The catalogue omits it for a reason we have not named; do not guess.
    return { code: "unknown_field", message: `"${id}" is not available here.` };
  }
  return { code: "unknown_field", message: `"${id}" is not a field of this domain.` };
}

const TYPE_MESSAGE: Record<AttrType, string> = {
  integer: "must be a whole number, such as 8 or -2 (no decimals).",
  number: "must be a number, such as 2.5.",
  text: "must be text.",
  boolean: "must be True or False.",
  enum: "must be one of the allowed values.",
  date: "must be a date (YYYY-MM-DD).",
  time: "must be a time of day (HH:MM).",
};

/** Whether one value fits `field`'s data type, or why not. */
function scalarProblem(field: ExpressionField, value: unknown): string | null {
  const type = field.dataType;
  switch (type) {
    case "integer":
      if (typeof value !== "number" || !Number.isSafeInteger(value)) return TYPE_MESSAGE.integer;
      return null;
    case "number":
      if (typeof value !== "number" || !Number.isFinite(value)) return TYPE_MESSAGE.number;
      return null;
    case "boolean":
      return typeof value === "boolean" ? null : TYPE_MESSAGE.boolean;
    case "text":
      return typeof value === "string" ? null : TYPE_MESSAGE.text;
    case "enum":
      if (typeof value !== "string") return TYPE_MESSAGE.enum;
      return (field.enumValues ?? []).includes(value)
        ? null
        : `"${value}" is not one of ${(field.enumValues ?? []).join(", ")}.`;
    case "date":
    case "time": {
      if (typeof value !== "string" || value === "") return TYPE_MESSAGE[type];
      // The same calendar/clock rules the attribute editor applies, from
      // the same function, so a date this app refuses to store is also one
      // it refuses to filter by.
      const parsed = parseAttrValue(type, value, [], "value");
      return parsed.ok ? null : TYPE_MESSAGE[type];
    }
  }
}

function valueProblem(
  field: ExpressionField,
  operator: string,
  value: unknown
): { code: ExpressionProblemCode; message: string } | null {
  const arity = EXPRESSION_OPERATORS[operator].arity;
  if (arity === "unary") return null;
  if (arity === "list") {
    if (!Array.isArray(value)) {
      return { code: "bad_value_type", message: `${field.label}: "is one of" takes a list of values.` };
    }
    if (value.length === 0) {
      return { code: "empty_list", message: `${field.label}: choose at least one value.` };
    }
    for (const item of value) {
      const problem = scalarProblem(field, item);
      if (problem) {
        return {
          code: field.dataType === "enum" && typeof item === "string" ? "bad_enum_value" : "bad_value_type",
          message: `${field.label}: ${problem}`,
        };
      }
    }
    return null;
  }
  const problem = scalarProblem(field, value);
  if (!problem) return null;
  return {
    code: field.dataType === "enum" && typeof value === "string" ? "bad_enum_value" : "bad_value_type",
    message: `${field.label}: ${problem}`,
  };
}

// --- the walk ---------------------------------------------------------------

type Walker = {
  problems: ExpressionProblem[];
  warnings: ExpressionWarning[];
  catalogue: FieldCatalogue;
};

function checkRule(w: Walker, rule: ExpressionRule, path: number[]): ExpressionField | null {
  const field = w.catalogue.get(rule.field);
  if (!field) {
    const { code, message } = fieldProblem(rule.field, w.catalogue);
    w.problems.push({ path, code, message });
    return null;
  }
  if (!EXPRESSION_OPERATORS[rule.operator] || !fieldAllowsOperator(field, rule.operator)) {
    w.problems.push({
      path,
      code: "bad_operator",
      message: `${field.label}: "${rule.operator}" is not a comparison this field offers.`,
    });
    return field;
  }
  const problem = valueProblem(field, rule.operator, rule.value);
  if (problem) w.problems.push({ path, ...problem });
  return field;
}

/** The entity type a field belongs to, or null for a field every entity
 * has (a column, a relationship count). */
function entityTypeOf(field: ExpressionField): string | null {
  const ref = field.ref;
  if (ref.kind === "attribute") return ref.entityTypeId;
  if (ref.kind === "function" && ref.argument.kind === "attribute") return ref.argument.entityTypeId;
  return null;
}

/**
 * Walks a group, and returns the entity types its conjunction REQUIRES.
 *
 * A plain (un-negated) `and` sub-group is part of the same conjunction as
 * its parent, so its types propagate up: the first browser run showed the
 * warning silently disappearing the moment the second rule was moved into
 * a group, although nothing could satisfy it either way. An `or` group can
 * be satisfied by either branch, and a negated group requires nothing, so
 * neither propagates.
 */
function checkGroup(w: Walker, group: unknown, path: number[], depth: number): Set<string> {
  const none = new Set<string>();
  if (!isPlainObject(group)) {
    w.problems.push({ path, code: "malformed", message: "This group is not an object." });
    return none;
  }
  if (group.combinator !== "and" && group.combinator !== "or") {
    w.problems.push({
      path,
      code: "bad_combinator",
      message: `A group joins its conditions with "and" or "or", not "${String(group.combinator)}".`,
    });
    return none;
  }
  if (!Array.isArray(group.rules)) {
    w.problems.push({ path, code: "malformed", message: "This group's conditions are not a list." });
    return none;
  }
  if (depth > MAX_DEPTH) {
    w.problems.push({
      path,
      code: "too_deep",
      message: `Groups are nested more than ${MAX_DEPTH} deep.`,
    });
    return none;
  }

  const entityTypes = new Set<string>();
  group.rules.forEach((node, index) => {
    const childPath = [...path, index];
    if (!isPlainObject(node)) {
      w.problems.push({ path: childPath, code: "malformed", message: "This condition is not an object." });
      return;
    }
    if (Array.isArray(node.rules)) {
      const inner = checkGroup(w, node, childPath, depth + 1);
      // `checkGroup` already returns nothing for an `or` group, so the
      // only thing left to decide here is negation. Checking the
      // combinator again was an equivalent mutant -- two places deciding
      // one thing, and a test could not tell which was deciding it.
      if (!node.not) {
        for (const id of inner) entityTypes.add(id);
      }
      return;
    }
    if (typeof node.field !== "string" || typeof node.operator !== "string") {
      w.problems.push({
        path: childPath,
        code: "malformed",
        message: "A condition needs a field and a comparison.",
      });
      return;
    }
    const field = checkRule(w, node as unknown as ExpressionRule, childPath);
    if (field) {
      const entityType = entityTypeOf(field);
      if (entityType) entityTypes.add(entityType);
    }
  });

  if (group.combinator === "and" && entityTypes.size > 1) {
    w.warnings.push({
      path,
      code: "mixed_entity_types",
      message:
        "These conditions name attributes of different entity types, joined by “and”. " +
        "An entity has one type, so nothing can satisfy all of them — use “or”.",
    });
  }
  return group.combinator === "and" ? entityTypes : none;
}

export function validateExpression(input: unknown, catalogue: FieldCatalogue): ValidationResult {
  const fallback = { version: EXPRESSION_VERSION, query: { combinator: "and", rules: [] } } as ExpressionDocument;
  const fail = (code: ExpressionProblemCode, message: string): ValidationResult => ({
    valid: false,
    problems: [{ path: [], code, message }],
    warnings: [],
    document: fallback,
  });

  if (!isPlainObject(input)) {
    return fail("malformed", "An expression is an object with a version and a query.");
  }
  if (input.version !== EXPRESSION_VERSION) {
    return fail(
      "unsupported_version",
      `This expression says version ${JSON.stringify(input.version)}; this app writes version ${EXPRESSION_VERSION}.`
    );
  }
  if (!isPlainObject(input.query)) {
    return fail("malformed", "An expression is an object with a version and a query.");
  }

  const w: Walker = { problems: [], warnings: [], catalogue };
  checkGroup(w, input.query, [], 1);
  return {
    valid: w.problems.length === 0,
    problems: w.problems,
    warnings: w.warnings,
    document: w.problems.length === 0 ? ({ version: EXPRESSION_VERSION, query: input.query } as ExpressionDocument) : fallback,
  };
}

/** The subset of `validateExpression` a consumer that only wants a yes/no
 * needs. */
export function isValidExpression(input: unknown, catalogue: FieldCatalogue): input is ExpressionDocument {
  return validateExpression(input, catalogue).valid;
}

export type { ExpressionGroup };
