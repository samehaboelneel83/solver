import { describe, expect, it } from "vitest";
import { EXPRESSION_VERSION, emptyDocument, type ExpressionDocument } from "./document";
import { buildFieldCatalogue, encodeFieldId } from "./fields";
import { MAX_DEPTH, MAX_LIST_LENGTH, MAX_RULES, validateExpression } from "./validate";
import { ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * Every case below is wrong in EXACTLY ONE way, and asserts the code that
 * fired -- not merely that something failed. A document that is invalid
 * for two reasons at once cannot show which rule caught it, so it cannot
 * tell a working validator from one that returns "invalid" unconditionally.
 *
 * The valid counterpart of each case is asserted alongside it, for the
 * same reason in reverse.
 */

// No columns: the graph is the first consumer, and its payload carries
// none of the entity's own columns faithfully. A consumer that has them
// passes them in, which is what the `withColumns` case below checks.
const catalogue = buildFieldCatalogue({
  entityTypes: ENTITY_TYPES,
  relationshipTypes: RELATIONSHIP_TYPES,
  columns: [],
});

const CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" }); // integer, required
const GRADE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "grade" }); // number, optional
const CODE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "code" }); // text
const ACTIVE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "active" }); // boolean
const BAND = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "band" }); // enum low|high
const OPENED = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "opened" }); // date
const STARTS = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "starts" }); // time
const SHIFT_CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" }); // number

function doc(...rules: unknown[]): unknown {
  return { version: EXPRESSION_VERSION, query: { combinator: "and", rules } };
}

function codes(input: unknown): string[] {
  return validateExpression(input, catalogue).problems.map((p) => p.code);
}

describe("validateExpression — the document itself", () => {
  it("accepts an empty document", () => {
    const result = validateExpression(emptyDocument(), catalogue);
    expect(result.valid).toBe(true);
    expect(result.problems).toEqual([]);
  });

  it("refuses a version it does not understand, and accepts the one it does", () => {
    expect(codes({ version: 2, query: { combinator: "and", rules: [] } })).toEqual(["unsupported_version"]);
    expect(codes({ version: "1", query: { combinator: "and", rules: [] } })).toEqual(["unsupported_version"]);
    expect(codes({ query: { combinator: "and", rules: [] } })).toEqual(["unsupported_version"]);
    expect(codes({ version: 1, query: { combinator: "and", rules: [] } })).toEqual([]);
  });

  it("refuses a document that is not an object at all", () => {
    for (const bad of [null, 7, "nope", []]) {
      expect(codes(bad), JSON.stringify(bad)).toEqual(["malformed"]);
    }
  });

  it("refuses a missing or non-object query", () => {
    expect(codes({ version: 1 })).toEqual(["malformed"]);
    expect(codes({ version: 1, query: "and" })).toEqual(["malformed"]);
  });

  it("refuses a combinator that is not and/or", () => {
    expect(codes({ version: 1, query: { combinator: "xor", rules: [] } })).toEqual(["bad_combinator"]);
    expect(codes({ version: 1, query: { combinator: "or", rules: [] } })).toEqual([]);
  });

  it("refuses rules that are not a list", () => {
    expect(codes({ version: 1, query: { combinator: "and", rules: {} } })).toEqual(["malformed"]);
  });

  it("refuses a document nested deeper than it will evaluate", () => {
    const deep = (depth: number): unknown =>
      depth === 0 ? { field: CODE, operator: "=", value: "x" } : { combinator: "and", rules: [deep(depth - 1)] };
    expect(codes({ version: 1, query: deep(MAX_DEPTH) })).toEqual([]);
    expect(codes({ version: 1, query: deep(MAX_DEPTH + 1) })).toEqual(["too_deep"]);
  });
});

describe("validateExpression — fields", () => {
  it("refuses a field the catalogue does not hold, and accepts one it does", () => {
    expect(codes(doc({ field: "attr:99:nope", operator: "=", value: 1 }))).toEqual(["unknown_field"]);
    expect(codes(doc({ field: CAPACITY, operator: "=", value: 1 }))).toEqual([]);
  });

  it("refuses a bare attribute name, because a name is not an identity", () => {
    expect(codes(doc({ field: "capacity", operator: "=", value: 1 }))).toEqual(["unknown_field"]);
  });

  it("refuses a column the consumer did not offer", () => {
    // The graph payload carries none of the entity's own columns, so its
    // catalogue omits them; the same document is fine where they exist.
    const withColumns = buildFieldCatalogue({ entityTypes: ENTITY_TYPES, columns: ["key"] });
    const field = encodeFieldId({ kind: "column", column: "key" });
    const input = doc({ field, operator: "=", value: "u1" });
    expect(validateExpression(input, catalogue).problems.map((p) => p.code)).toEqual(["unknown_field"]);
    expect(validateExpression(input, withColumns).problems).toEqual([]);
  });

  it("names the offending rule's path, so the builder can point at it", () => {
    const input = {
      version: 1,
      query: {
        combinator: "and",
        rules: [
          { field: CODE, operator: "=", value: "x" },
          { combinator: "or", rules: [{ field: "attr:99:nope", operator: "=", value: 1 }] },
        ],
      },
    };
    const problems = validateExpression(input, catalogue).problems;
    expect(problems).toHaveLength(1);
    expect(problems[0].path).toEqual([1, 0]);
  });
});

describe("validateExpression — function calls", () => {
  it("refuses a function that is not in the catalogue", () => {
    expect(codes(doc({ field: `fn:sqrt:${CAPACITY}`, operator: "=", value: 1 }))).toEqual(["unknown_function"]);
  });

  it("refuses a function applied to an argument type it is not defined on", () => {
    // `code` is text. The check is on the DECLARED data type: a text
    // attribute whose values happen to look like years is still text.
    expect(codes(doc({ field: `fn:year:${CODE}`, operator: "=", value: 2026 }))).toEqual(["bad_argument_type"]);
    expect(codes(doc({ field: `fn:year:${OPENED}`, operator: "=", value: 2026 }))).toEqual([]);
  });

  it("refuses hour on a date and year on a time, which differ only in the argument's type", () => {
    expect(codes(doc({ field: `fn:hour:${OPENED}`, operator: "=", value: 9 }))).toEqual(["bad_argument_type"]);
    expect(codes(doc({ field: `fn:hour:${STARTS}`, operator: "=", value: 9 }))).toEqual([]);
    expect(codes(doc({ field: `fn:year:${STARTS}`, operator: "=", value: 2026 }))).toEqual(["bad_argument_type"]);
  });

  it("refuses a nested call, which version 1 does not express", () => {
    expect(codes(doc({ field: `fn:abs:fn:year:${OPENED}`, operator: "=", value: 1 }))).toEqual([
      "nested_function",
    ]);
  });

  it("refuses a call whose argument field does not exist", () => {
    expect(codes(doc({ field: "fn:year:attr:99:nope", operator: "=", value: 1 }))).toEqual(["unknown_field"]);
  });

  it("checks a count's value against integer, not against its relationship", () => {
    const count = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "10", direction: "incoming" },
    });
    expect(codes(doc({ field: count, operator: ">", value: 2 }))).toEqual([]);
    expect(codes(doc({ field: count, operator: ">", value: 2.5 }))).toEqual(["bad_value_type"]);
  });

  it("refuses a count over a relationship type the domain does not have", () => {
    const count = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "999", direction: "any" },
    });
    expect(codes(doc({ field: count, operator: ">", value: 1 }))).toEqual(["unknown_field"]);
  });
});

describe("validateExpression — operators", () => {
  it("refuses an operator the field's data type does not offer", () => {
    expect(codes(doc({ field: ACTIVE, operator: ">", value: true }))).toEqual(["bad_operator"]);
    expect(codes(doc({ field: CODE, operator: ">", value: "a" }))).toEqual(["bad_operator"]);
    expect(codes(doc({ field: CAPACITY, operator: "contains", value: 1 }))).toEqual(["bad_operator"]);
  });

  it("accepts the operators the field's data type does offer", () => {
    expect(codes(doc({ field: ACTIVE, operator: "=", value: true }))).toEqual([]);
    expect(codes(doc({ field: CODE, operator: "contains", value: "a" }))).toEqual([]);
    expect(codes(doc({ field: CAPACITY, operator: ">", value: 1 }))).toEqual([]);
  });

  it("refuses an operator that is not in the table at all", () => {
    expect(codes(doc({ field: CODE, operator: "sortaLike", value: "a" }))).toEqual(["bad_operator"]);
  });

  it("refuses is-empty on a required field and allows it on an optional one", () => {
    expect(codes(doc({ field: CAPACITY, operator: "null", value: null }))).toEqual(["bad_operator"]);
    expect(codes(doc({ field: GRADE, operator: "null", value: null }))).toEqual([]);
  });
});

describe("validateExpression — value types", () => {
  it("refuses a string where an integer field needs a number", () => {
    // This is the case the value editor produces while the user is typing
    // something that is not yet a number, so it has to be caught here
    // rather than by each consumer.
    expect(codes(doc({ field: CAPACITY, operator: "=", value: "8" }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: CAPACITY, operator: "=", value: 8 }))).toEqual([]);
  });

  it("refuses a decimal on an integer field and accepts it on a number one", () => {
    expect(codes(doc({ field: CAPACITY, operator: "=", value: 2.5 }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: SHIFT_CAPACITY, operator: "=", value: 2.5 }))).toEqual([]);
  });

  it("refuses a non-finite number, which JSON cannot carry anyway", () => {
    expect(codes(doc({ field: GRADE, operator: "=", value: Number.NaN }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: GRADE, operator: "=", value: Number.POSITIVE_INFINITY }))).toEqual([
      "bad_value_type",
    ]);
  });

  it("refuses a string where a boolean field needs a boolean", () => {
    expect(codes(doc({ field: ACTIVE, operator: "=", value: "true" }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: ACTIVE, operator: "=", value: false }))).toEqual([]);
  });

  it("refuses a number where a text field needs a string", () => {
    expect(codes(doc({ field: CODE, operator: "=", value: 8 }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: CODE, operator: "=", value: "8" }))).toEqual([]);
  });

  it("refuses a date that is not a real calendar date", () => {
    expect(codes(doc({ field: OPENED, operator: "=", value: "2026-02-30" }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: OPENED, operator: "=", value: "2026-02-28" }))).toEqual([]);
  });

  it("refuses a time that is not a time of day", () => {
    expect(codes(doc({ field: STARTS, operator: "=", value: "25:00" }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: STARTS, operator: "=", value: "09:30" }))).toEqual([]);
  });

  it("refuses an enum value that is not one of that attribute's own", () => {
    // `medium` is a perfectly good string; it is only wrong against THIS
    // attribute's enum_values.
    expect(codes(doc({ field: BAND, operator: "=", value: "medium" }))).toEqual(["bad_enum_value"]);
    expect(codes(doc({ field: BAND, operator: "=", value: "high" }))).toEqual([]);
  });

  it("ignores the value of a unary operator", () => {
    // The builder leaves the previous operator's value behind when the
    // user switches to "is empty"; that is not an error.
    expect(codes(doc({ field: GRADE, operator: "notNull", value: "left over" }))).toEqual([]);
  });

  it("requires a list operator's value to be a non-empty list of that type", () => {
    expect(codes(doc({ field: BAND, operator: "in", value: ["low", "high"] }))).toEqual([]);
    expect(codes(doc({ field: BAND, operator: "in", value: [] }))).toEqual(["empty_list"]);
    expect(codes(doc({ field: BAND, operator: "in", value: "low" }))).toEqual(["bad_value_type"]);
    expect(codes(doc({ field: BAND, operator: "in", value: ["low", "medium"] }))).toEqual(["bad_enum_value"]);
  });
});

describe("validateExpression — warnings", () => {
  it("warns when an and-group mixes attributes of two entity types, because a node has one type", () => {
    const input = doc(
      { field: CAPACITY, operator: ">", value: 1 },
      { field: SHIFT_CAPACITY, operator: ">", value: 1 }
    );
    const result = validateExpression(input, catalogue);
    expect(result.valid).toBe(true);
    expect(result.problems).toEqual([]);
    expect(result.warnings.map((w) => w.code)).toEqual(["mixed_entity_types"]);
  });

  it("does not warn when the same mix is joined by or", () => {
    const input = {
      version: 1,
      query: {
        combinator: "or",
        rules: [
          { field: CAPACITY, operator: ">", value: 1 },
          { field: SHIFT_CAPACITY, operator: ">", value: 1 },
        ],
      },
    };
    expect(validateExpression(input, catalogue).warnings).toEqual([]);
  });

  it("warns through a nested and-group, which is still one conjunction", () => {
    // Found in the browser: the same two rules with the second one inside a
    // group produced no warning at all, although nothing can satisfy it.
    const input = {
      version: 1,
      query: {
        combinator: "and",
        rules: [
          { field: CAPACITY, operator: ">", value: 1 },
          { combinator: "and", rules: [{ field: SHIFT_CAPACITY, operator: ">", value: 1 }] },
        ],
      },
    };
    expect(validateExpression(input, catalogue).warnings.map((w) => w.code)).toEqual(["mixed_entity_types"]);
  });

  it("does not warn through a nested or-group, which either branch can satisfy", () => {
    const input = {
      version: 1,
      query: {
        combinator: "and",
        rules: [
          { field: CAPACITY, operator: ">", value: 1 },
          {
            combinator: "or",
            rules: [
              { field: SHIFT_CAPACITY, operator: ">", value: 1 },
              { field: CODE, operator: "=", value: "x" },
            ],
          },
        ],
      },
    };
    expect(validateExpression(input, catalogue).warnings).toEqual([]);
  });

  it("does not warn through a negated nested and-group", () => {
    const input = {
      version: 1,
      query: {
        combinator: "and",
        rules: [
          { field: CAPACITY, operator: ">", value: 1 },
          { combinator: "and", not: true, rules: [{ field: SHIFT_CAPACITY, operator: ">", value: 1 }] },
        ],
      },
    };
    expect(validateExpression(input, catalogue).warnings).toEqual([]);
  });

  it("does not warn about two attributes of the same entity type under and", () => {
    expect(
      validateExpression(doc({ field: CAPACITY, operator: ">", value: 1 }, { field: CODE, operator: "=", value: "x" }), catalogue)
        .warnings
    ).toEqual([]);
  });
});

describe("validateExpression — the result a consumer reads", () => {
  it("says valid exactly when there are no problems, whatever the warnings", () => {
    const good = validateExpression(doc({ field: CODE, operator: "=", value: "x" }), catalogue);
    expect(good.valid).toBe(true);
    const bad = validateExpression(doc({ field: CODE, operator: "=", value: 1 }), catalogue);
    expect(bad.valid).toBe(false);
    expect(bad.problems).toHaveLength(1);
  });

  it("gives every problem a message a user could act on", () => {
    const bad = validateExpression(doc({ field: CAPACITY, operator: "=", value: "8" }), catalogue);
    expect(bad.problems[0].message).toMatch(/whole number/i);
    expect(bad.problems[0].message).toMatch(/capacity/);
  });

  it("narrows a checked document to the document type", () => {
    const input: unknown = doc({ field: CODE, operator: "=", value: "x" });
    const result = validateExpression(input, catalogue);
    if (!result.valid) throw new Error("fixture should be valid");
    const checked: ExpressionDocument = result.document;
    expect(checked.version).toBe(EXPRESSION_VERSION);
  });

  it("reports every bad rule, not just the first", () => {
    expect(
      codes(doc({ field: CODE, operator: "=", value: 1 }, { field: ACTIVE, operator: "=", value: "yes" }))
    ).toEqual(["bad_value_type", "bad_value_type"]);
  });
});

/**
 * The two size limits the client shares with Task 14d's compiler
 * (`backend/app/expressions/catalogue.json`, `parity.test.ts` pins the
 * numbers). They exist so the browser refuses what the server would refuse
 * rather than sending it and being told 422 -- which means the boundary
 * itself has to be tested, not just the numbers.
 */
describe("validateExpression — the shared size limits", () => {
  const rules = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ field: CAPACITY, operator: "=", value: i }));

  it("accepts exactly the rule limit and refuses one more", () => {
    expect(codes({ version: 1, query: { combinator: "and", rules: rules(MAX_RULES) } })).toEqual([]);
    expect(codes({ version: 1, query: { combinator: "and", rules: rules(MAX_RULES + 1) } })).toEqual([
      "too_many_rules",
    ]);
  });

  it("counts rules at every depth, not only the root group's", () => {
    const nested = {
      version: 1,
      query: {
        combinator: "and",
        rules: [
          { combinator: "or", rules: rules(MAX_RULES) },
          { field: CAPACITY, operator: "=", value: 0 },
        ],
      },
    };
    expect(codes(nested)).toEqual(["too_many_rules"]);
  });

  it("accepts exactly the value-list limit and refuses one more", () => {
    const list = (n: number) => Array.from({ length: n }, () => "low");
    expect(codes(doc({ field: BAND, operator: "in", value: list(MAX_LIST_LENGTH) }))).toEqual([]);
    expect(codes(doc({ field: BAND, operator: "in", value: list(MAX_LIST_LENGTH + 1) }))).toEqual([
      "list_too_long",
    ]);
  });
});
