import { describe, expect, it } from "vitest";
import { EXPRESSION_VERSION, type ExpressionDocument } from "./document";
import { buildFieldCatalogue, encodeFieldId } from "./fields";
import { degreeKey, evaluateExpression, type EvaluationTarget } from "./evaluate";
import { ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * Every test here asserts BOTH a match and a non-match against the same
 * expression. A filter that returned `true` for everything (or `false` for
 * everything) would satisfy half of each of these and fail the other half,
 * which is the only way to tell an evaluator from a constant.
 */

const catalogue = buildFieldCatalogue({
  entityTypes: ENTITY_TYPES,
  relationshipTypes: RELATIONSHIP_TYPES,
  columns: ["key", "label", "sort_order", "active"],
});

const CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" });
const GRADE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "grade" });
const CODE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "code" });
const ACTIVE_ATTR = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "active" });
const ACTIVE_COL = encodeFieldId({ kind: "column", column: "active" });
const KEY_COL = encodeFieldId({ kind: "column", column: "key" });
const BAND = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "band" });
const OPENED = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "opened" });
const STARTS = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "starts" });
const SHIFT_CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" });

function unit(attrs: Record<string, unknown>, columns: Partial<EvaluationTarget["columns"]> = {}): EvaluationTarget {
  return {
    entityTypeId: "1",
    attrs,
    columns: { key: "u1", label: "Unit one", sort_order: 0, active: true, ...columns },
    degrees: new Map(),
  };
}

function shift(attrs: Record<string, unknown>): EvaluationTarget {
  return {
    entityTypeId: "2",
    attrs,
    columns: { key: "s1", label: null, sort_order: 0, active: true },
    degrees: new Map(),
  };
}

function expr(...rules: unknown[]): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: { combinator: "and", rules } } as ExpressionDocument;
}

function or(...rules: unknown[]): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: { combinator: "or", rules } } as ExpressionDocument;
}

const run = (doc: ExpressionDocument, target: EvaluationTarget) => evaluateExpression(doc, catalogue, target);

describe("the empty expression", () => {
  it("matches everything, so it filters nothing", () => {
    const empty = { version: EXPRESSION_VERSION, query: { combinator: "and", rules: [] } } as ExpressionDocument;
    expect(run(empty, unit({ capacity: 1 }))).toBe(true);
    expect(run(empty, shift({}))).toBe(true);
  });
});

describe("comparison by data type", () => {
  it("compares integers numerically, not as text", () => {
    // "9" > "10" as strings; 9 > 10 is false. A string comparison would
    // pass the first of these and fail the second.
    const doc = expr({ field: CAPACITY, operator: ">", value: 9 });
    expect(run(doc, unit({ capacity: 10 }))).toBe(true);
    expect(run(doc, unit({ capacity: 9 }))).toBe(false);
    expect(run(doc, unit({ capacity: 2 }))).toBe(false);
  });

  it("orders each of <, <=, >, >= the right way round", () => {
    expect(run(expr({ field: CAPACITY, operator: "<", value: 5 }), unit({ capacity: 4 }))).toBe(true);
    expect(run(expr({ field: CAPACITY, operator: "<", value: 5 }), unit({ capacity: 5 }))).toBe(false);
    expect(run(expr({ field: CAPACITY, operator: "<=", value: 5 }), unit({ capacity: 5 }))).toBe(true);
    expect(run(expr({ field: CAPACITY, operator: "<=", value: 5 }), unit({ capacity: 6 }))).toBe(false);
    expect(run(expr({ field: CAPACITY, operator: ">=", value: 5 }), unit({ capacity: 5 }))).toBe(true);
    expect(run(expr({ field: CAPACITY, operator: ">=", value: 5 }), unit({ capacity: 4 }))).toBe(false);
  });

  it("compares numbers, including a decimal that would truncate to a match", () => {
    const doc = expr({ field: GRADE, operator: ">", value: 2.5 });
    expect(run(doc, unit({ grade: 2.6 }))).toBe(true);
    expect(run(doc, unit({ grade: 2.4 }))).toBe(false);
  });

  it("compares dates chronologically", () => {
    const doc = expr({ field: OPENED, operator: ">=", value: "2026-02-01" });
    expect(run(doc, unit({ opened: "2026-02-01" }))).toBe(true);
    expect(run(doc, unit({ opened: "2026-10-01" }))).toBe(true);
    expect(run(doc, unit({ opened: "2025-12-31" }))).toBe(false);
  });

  it("compares times of day, whatever precision they were stored with", () => {
    // "09:30:00" and "09:30" are the same instant; a lexicographic compare
    // of the raw strings gets one of these pairs wrong.
    const doc = expr({ field: STARTS, operator: ">=", value: "09:30" });
    expect(run(doc, unit({ starts: "09:30:00" }))).toBe(true);
    expect(run(doc, unit({ starts: "10:00" }))).toBe(true);
    expect(run(doc, unit({ starts: "09:29:59" }))).toBe(false);
  });

  it("makes two spellings of the same time EQUAL, and two different times not", () => {
    // "09:30" and "09:30:00" are the same instant, and `=` has to say so:
    // strict string equality (which is what `=` did until a surviving
    // mutant showed this case was untested) calls them different, so a
    // filter on 09:30 would silently miss every row stored with seconds.
    const doc = expr({ field: STARTS, operator: "=", value: "09:30" });
    expect(run(doc, unit({ starts: "09:30:00" }))).toBe(true);
    expect(run(doc, unit({ starts: "09:30" }))).toBe(true);
    expect(run(doc, unit({ starts: "09:31" }))).toBe(false);
    const not = expr({ field: STARTS, operator: "!=", value: "09:30" });
    expect(run(not, unit({ starts: "09:31" }))).toBe(true);
    expect(run(not, unit({ starts: "09:30:00" }))).toBe(false);
  });

  it("keeps text equality strict while doing so", () => {
    // The same code path serves text; folding case in here would undo the
    // case sensitivity asserted below.
    expect(run(expr({ field: CODE, operator: "=", value: "ab" }), unit({ code: "ab" }))).toBe(true);
    expect(run(expr({ field: CODE, operator: "=", value: "ab" }), unit({ code: "AB" }))).toBe(false);
  });

  it("compares booleans, and does not treat every present value as true", () => {
    const doc = expr({ field: ACTIVE_ATTR, operator: "=", value: true });
    expect(run(doc, unit({ active: true }))).toBe(true);
    expect(run(doc, unit({ active: false }))).toBe(false);
    const off = expr({ field: ACTIVE_ATTR, operator: "=", value: false });
    expect(run(off, unit({ active: false }))).toBe(true);
    expect(run(off, unit({ active: true }))).toBe(false);
  });

  it("makes text equality case-SENSITIVE, as SQL `=` is", () => {
    const doc = expr({ field: CODE, operator: "=", value: "AB" });
    expect(run(doc, unit({ code: "AB" }))).toBe(true);
    expect(run(doc, unit({ code: "ab" }))).toBe(false);
  });

  it("makes contains / starts with / ends with case-INSENSITIVE, as ILIKE is", () => {
    expect(run(expr({ field: CODE, operator: "contains", value: "bc" }), unit({ code: "ABCD" }))).toBe(true);
    expect(run(expr({ field: CODE, operator: "contains", value: "bc" }), unit({ code: "ACBD" }))).toBe(false);
    expect(run(expr({ field: CODE, operator: "beginsWith", value: "ab" }), unit({ code: "ABCD" }))).toBe(true);
    expect(run(expr({ field: CODE, operator: "beginsWith", value: "bc" }), unit({ code: "ABCD" }))).toBe(false);
    expect(run(expr({ field: CODE, operator: "endsWith", value: "cd" }), unit({ code: "ABCD" }))).toBe(true);
    expect(run(expr({ field: CODE, operator: "endsWith", value: "ab" }), unit({ code: "ABCD" }))).toBe(false);
    expect(run(expr({ field: CODE, operator: "doesNotContain", value: "zz" }), unit({ code: "ABCD" }))).toBe(true);
    expect(run(expr({ field: CODE, operator: "doesNotContain", value: "bc" }), unit({ code: "ABCD" }))).toBe(false);
  });

  it("treats a substring pattern as text, not as a wildcard pattern", () => {
    // `%` is a SQL wildcard; here it is an ordinary character, and Task 14d
    // has to escape it rather than pass it through.
    const doc = expr({ field: CODE, operator: "contains", value: "%" });
    expect(run(doc, unit({ code: "a%b" }))).toBe(true);
    expect(run(doc, unit({ code: "ab" }))).toBe(false);
  });

  it("matches enum membership against the listed values", () => {
    const doc = expr({ field: BAND, operator: "in", value: ["low"] });
    expect(run(doc, unit({ band: "low" }))).toBe(true);
    expect(run(doc, unit({ band: "high" }))).toBe(false);
    const not = expr({ field: BAND, operator: "notIn", value: ["low"] });
    expect(run(not, unit({ band: "high" }))).toBe(true);
    expect(run(not, unit({ band: "low" }))).toBe(false);
  });
});

describe("absent values", () => {
  it("matches is-empty on an absent attribute and not on a present one", () => {
    const doc = expr({ field: GRADE, operator: "null", value: null });
    expect(run(doc, unit({}))).toBe(true);
    expect(run(doc, unit({ grade: null }))).toBe(true);
    expect(run(doc, unit({ grade: 0 }))).toBe(false);
  });

  it("matches is-not-empty on a present attribute, including a falsy one", () => {
    const doc = expr({ field: GRADE, operator: "notNull", value: null });
    expect(run(doc, unit({ grade: 0 }))).toBe(true);
    expect(run(doc, unit({}))).toBe(false);
  });

  it("does not match a comparison against an absent value, as SQL's NULL does not", () => {
    // Both directions: neither `> 5` nor `<= 5` is true of a missing value.
    expect(run(expr({ field: GRADE, operator: ">", value: 5 }), unit({}))).toBe(false);
    expect(run(expr({ field: GRADE, operator: "<=", value: 5 }), unit({}))).toBe(false);
    expect(run(expr({ field: GRADE, operator: ">", value: 5 }), unit({ grade: 6 }))).toBe(true);
  });

  it("does not match an entity of a different type, because the attribute is not its own", () => {
    // `attr:1:capacity` names UNIT's capacity. A shift has a `capacity`
    // too, of a different type; matching it would be matching by name.
    const doc = expr({ field: CAPACITY, operator: ">", value: 1 });
    expect(run(doc, unit({ capacity: 5 }))).toBe(true);
    expect(run(doc, shift({ capacity: 5 }))).toBe(false);
    const other = expr({ field: SHIFT_CAPACITY, operator: ">", value: 1 });
    expect(run(other, shift({ capacity: 5 }))).toBe(true);
    expect(run(other, unit({ capacity: 5 }))).toBe(false);
  });

  it("is false for an entity of another type whatever the operator, including is-empty", () => {
    // Found in the browser: with "absent" and "not this entity's field"
    // collapsed into one state, `unit.note is empty` also matched every
    // SHIFT, because a shift has no `unit.note` either. A rule about one
    // type's attribute carries that type with it -- which is also how Task
    // 14d compiles it (`entity_type_id = :t AND ...`).
    expect(run(expr({ field: GRADE, operator: "null", value: null }), unit({}))).toBe(true);
    expect(run(expr({ field: GRADE, operator: "null", value: null }), shift({}))).toBe(false);
    expect(run(expr({ field: GRADE, operator: "notNull", value: null }), unit({ grade: 1 }))).toBe(true);
    expect(run(expr({ field: GRADE, operator: "notNull", value: null }), shift({ grade: 1 }))).toBe(false);
    // ...and a function over it behaves the same way.
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: ">", value: 0 }), unit({ opened: "2026-01-01" }))).toBe(true);
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: ">", value: 0 }), shift({ opened: "2026-01-01" }))).toBe(false);
  });

  it("still applies a relationship count to every entity, whatever its type", () => {
    // A count is not any one type's field, so it must NOT be narrowed the
    // way an attribute is.
    const field = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "10", direction: "outgoing" },
    });
    const withEdges = new Map([[degreeKey("10", "outgoing"), 2]]);
    expect(run(expr({ field, operator: ">", value: 1 }), { ...shift({}), degrees: withEdges })).toBe(true);
    expect(run(expr({ field, operator: ">", value: 1 }), shift({}))).toBe(false);
  });

  it("reads a column from the columns, and a same-named attribute from the attrs", () => {
    const byColumn = expr({ field: ACTIVE_COL, operator: "=", value: true });
    const byAttribute = expr({ field: ACTIVE_ATTR, operator: "=", value: true });
    const target = unit({ active: false }, { active: true });
    expect(run(byColumn, target)).toBe(true);
    expect(run(byAttribute, target)).toBe(false);
    const flipped = unit({ active: true }, { active: false });
    expect(run(byColumn, flipped)).toBe(false);
    expect(run(byAttribute, flipped)).toBe(true);
  });

  it("reads a text column", () => {
    const doc = expr({ field: KEY_COL, operator: "beginsWith", value: "u" });
    expect(run(doc, unit({}, { key: "u9" }))).toBe(true);
    expect(run(doc, unit({}, { key: "s9" }))).toBe(false);
  });
});

describe("functions", () => {
  it("evaluates year, month and day of a date", () => {
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: "=", value: 2026 }), unit({ opened: "2026-03-04" }))).toBe(true);
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: "=", value: 2026 }), unit({ opened: "2025-03-04" }))).toBe(false);
    expect(run(expr({ field: `fn:month:${OPENED}`, operator: "=", value: 3 }), unit({ opened: "2026-03-04" }))).toBe(true);
    expect(run(expr({ field: `fn:month:${OPENED}`, operator: "=", value: 3 }), unit({ opened: "2026-04-04" }))).toBe(false);
    expect(run(expr({ field: `fn:day:${OPENED}`, operator: "=", value: 4 }), unit({ opened: "2026-03-04" }))).toBe(true);
    expect(run(expr({ field: `fn:day:${OPENED}`, operator: "=", value: 4 }), unit({ opened: "2026-03-05" }))).toBe(false);
  });

  it("evaluates hour and minute of a time", () => {
    expect(run(expr({ field: `fn:hour:${STARTS}`, operator: "=", value: 9 }), unit({ starts: "09:30" }))).toBe(true);
    expect(run(expr({ field: `fn:hour:${STARTS}`, operator: "=", value: 9 }), unit({ starts: "10:30" }))).toBe(false);
    expect(run(expr({ field: `fn:minute:${STARTS}`, operator: "=", value: 30 }), unit({ starts: "09:30" }))).toBe(true);
    expect(run(expr({ field: `fn:minute:${STARTS}`, operator: "=", value: 30 }), unit({ starts: "09:31" }))).toBe(false);
  });

  it("evaluates lower, upper and length of text", () => {
    expect(run(expr({ field: `fn:lower:${CODE}`, operator: "=", value: "ab" }), unit({ code: "AB" }))).toBe(true);
    expect(run(expr({ field: `fn:lower:${CODE}`, operator: "=", value: "ab" }), unit({ code: "AC" }))).toBe(false);
    expect(run(expr({ field: `fn:upper:${CODE}`, operator: "=", value: "AB" }), unit({ code: "ab" }))).toBe(true);
    expect(run(expr({ field: `fn:upper:${CODE}`, operator: "=", value: "AB" }), unit({ code: "ac" }))).toBe(false);
    expect(run(expr({ field: `fn:length:${CODE}`, operator: "=", value: 3 }), unit({ code: "abc" }))).toBe(true);
    expect(run(expr({ field: `fn:length:${CODE}`, operator: "=", value: 3 }), unit({ code: "ab" }))).toBe(false);
  });

  it("evaluates abs, which is the reason a negative and its magnitude differ", () => {
    const doc = expr({ field: `fn:abs:${GRADE}`, operator: ">", value: 2 });
    expect(run(doc, unit({ grade: -3 }))).toBe(true);
    expect(run(doc, unit({ grade: 3 }))).toBe(true);
    expect(run(doc, unit({ grade: -1 }))).toBe(false);
    // ...and without abs, the negative does not match, which is what makes
    // the assertion above about abs rather than about `>`.
    expect(run(expr({ field: GRADE, operator: ">", value: 2 }), unit({ grade: -3 }))).toBe(false);
  });

  it("does not match a function over an absent argument", () => {
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: ">", value: 0 }), unit({}))).toBe(false);
    expect(run(expr({ field: `fn:year:${OPENED}`, operator: ">", value: 0 }), unit({ opened: "2026-01-01" }))).toBe(true);
  });

  it("counts relationships in the direction asked for", () => {
    const outgoing = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "10", direction: "outgoing" },
    });
    const incoming = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "10", direction: "incoming" },
    });
    const target: EvaluationTarget = {
      ...unit({}),
      degrees: new Map([
        [degreeKey("10", "outgoing"), 3],
        [degreeKey("10", "incoming"), 0],
      ]),
    };
    expect(run(expr({ field: outgoing, operator: ">", value: 2 }), target)).toBe(true);
    expect(run(expr({ field: incoming, operator: ">", value: 2 }), target)).toBe(false);
    expect(run(expr({ field: incoming, operator: "=", value: 0 }), target)).toBe(true);
  });

  it("counts an unrecorded relationship as zero, not as absent", () => {
    const any = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "11", direction: "any" },
    });
    const target = unit({});
    expect(run(expr({ field: any, operator: "=", value: 0 }), target)).toBe(true);
    expect(run(expr({ field: any, operator: ">", value: 0 }), target)).toBe(false);
  });
});

describe("combinators", () => {
  it("requires every rule of an and-group", () => {
    const doc = expr(
      { field: CAPACITY, operator: ">", value: 2 },
      { field: CODE, operator: "contains", value: "a" }
    );
    expect(run(doc, unit({ capacity: 5, code: "abc" }))).toBe(true);
    expect(run(doc, unit({ capacity: 5, code: "xyz" }))).toBe(false);
    expect(run(doc, unit({ capacity: 1, code: "abc" }))).toBe(false);
  });

  it("requires one rule of an or-group", () => {
    const doc = or(
      { field: CAPACITY, operator: ">", value: 2 },
      { field: CODE, operator: "contains", value: "a" }
    );
    expect(run(doc, unit({ capacity: 5, code: "xyz" }))).toBe(true);
    expect(run(doc, unit({ capacity: 1, code: "abc" }))).toBe(true);
    expect(run(doc, unit({ capacity: 1, code: "xyz" }))).toBe(false);
  });

  it("negates a group with `not`", () => {
    const doc = {
      version: EXPRESSION_VERSION,
      query: { combinator: "and", not: true, rules: [{ field: CAPACITY, operator: ">", value: 2 }] },
    } as ExpressionDocument;
    expect(run(doc, unit({ capacity: 1 }))).toBe(true);
    expect(run(doc, unit({ capacity: 5 }))).toBe(false);
  });

  it("nests groups", () => {
    const doc = expr(
      { field: CODE, operator: "beginsWith", value: "a" },
      {
        combinator: "or",
        rules: [
          { field: CAPACITY, operator: ">", value: 8 },
          { field: BAND, operator: "=", value: "high" },
        ],
      }
    );
    expect(run(doc, unit({ code: "abc", capacity: 9, band: "low" }))).toBe(true);
    expect(run(doc, unit({ code: "abc", capacity: 1, band: "high" }))).toBe(true);
    expect(run(doc, unit({ code: "abc", capacity: 1, band: "low" }))).toBe(false);
    expect(run(doc, unit({ code: "zzz", capacity: 9, band: "high" }))).toBe(false);
  });

  it("treats an empty nested group as no constraint rather than as no match", () => {
    const doc = expr({ field: CAPACITY, operator: ">", value: 2 }, { combinator: "and", rules: [] });
    expect(run(doc, unit({ capacity: 5 }))).toBe(true);
    expect(run(doc, unit({ capacity: 1 }))).toBe(false);
  });
});

describe("a rule the catalogue cannot resolve", () => {
  it("matches nothing rather than everything", () => {
    // Callers validate first; if one does not, the safe failure is an
    // expression that visibly matches nothing, not one that silently
    // stops filtering.
    const doc = expr({ field: "attr:99:nope", operator: "=", value: 1 });
    expect(run(doc, unit({ capacity: 5 }))).toBe(false);
    expect(run(doc, shift({}))).toBe(false);
  });
});
