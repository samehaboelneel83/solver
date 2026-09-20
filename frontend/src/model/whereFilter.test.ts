import { describe, expect, it } from "vitest";
import { attributeName, fromIrWhere, toIrWhere } from "./whereFilter";
import type { ExpressionDocument } from "../expressions";

function doc(query: Record<string, unknown>): ExpressionDocument {
  return { version: 1, query } as unknown as ExpressionDocument;
}

describe("toIrWhere", () => {
  it("converts a flat and-list, which is what the IR admits", () => {
    const result = toIrWhere(
      doc({
        combinator: "and",
        rules: [
          { field: "attr:5:is_weekend", operator: "=", value: true },
          { field: "attr:5:rank", operator: ">=", value: 3 },
        ],
      })
    );

    expect(result).toEqual({
      ok: true,
      where: [
        { attr: "is_weekend", op: "=", value: true },
        { attr: "rank", op: ">=", value: 3 },
      ],
    });
  });

  it("refuses `or` rather than quietly turning it into `and`", () => {
    // Flattening would change which entities the constraint ranges over,
    // and nothing downstream could tell that had happened.
    const result = toIrWhere(
      doc({
        combinator: "or",
        rules: [
          { field: "attr:5:is_weekend", operator: "=", value: true },
          { field: "attr:5:is_weekend", operator: "=", value: false },
        ],
      })
    );

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.problems[0]).toMatch(/joins its conditions with and/i);
  });

  it("refuses a nested group", () => {
    const result = toIrWhere(
      doc({
        combinator: "and",
        rules: [
          { field: "attr:5:rank", operator: ">=", value: 3 },
          { combinator: "and", rules: [{ field: "attr:5:rank", operator: "<=", value: 9 }] },
        ],
      })
    );

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.problems.join(" ")).toMatch(/no groups/i);
  });

  it("refuses a negated filter", () => {
    const result = toIrWhere(
      doc({ combinator: "and", not: true, rules: [{ field: "attr:5:rank", operator: "=", value: 1 }] })
    );

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.problems[0]).toMatch(/cannot be negated/i);
  });

  it("refuses a field that is not an attribute of the binding's own set", () => {
    // Columns and function calls are offered by the catalogue but a binding
    // filter is defined over attributes only (contract §4.1).
    const result = toIrWhere(
      doc({ combinator: "and", rules: [{ field: "col:key", operator: "=", value: "mon" }] })
    );

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.problems[0]).toMatch(/not an attribute/i);
  });

  it("refuses an operator the IR's filter vocabulary does not carry", () => {
    // `contains` is in the expression catalogue; `filterOperators` is a
    // subset of it, and the IR's is the smaller list.
    const result = toIrWhere(
      doc({ combinator: "and", rules: [{ field: "attr:5:name", operator: "contains", value: "a" }] })
    );

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.problems[0]).toMatch(/is not a comparison/i);
  });

  it("treats an absent document as no filter at all", () => {
    expect(toIrWhere(null)).toEqual({ ok: true, where: [] });
  });

  it("reports every problem, not only the first", () => {
    const result = toIrWhere(
      doc({
        combinator: "or",
        rules: [
          { field: "col:key", operator: "=", value: "mon" },
          { field: "attr:5:rank", operator: "contains", value: 3 },
        ],
      })
    );

    expect(result.ok === false && result.problems).toHaveLength(3);
  });
});

describe("fromIrWhere", () => {
  it("round-trips a filter back into a document the builder can edit", () => {
    const where = [
      { attr: "is_weekend", op: "=", value: true },
      { attr: "rank", op: ">=", value: 3 },
    ];

    const round = toIrWhere(fromIrWhere(where, 5));

    expect(round).toEqual({ ok: true, where });
  });

  it("gives an empty filter an editable empty document", () => {
    expect(fromIrWhere(undefined, 5).query.rules).toEqual([]);
  });
});

describe("attributeName", () => {
  it("reads the name out of a catalogue field id", () => {
    expect(attributeName("attr:5:hours_per_week")).toBe("hours_per_week");
  });

  it("returns null for anything that is not an attribute field", () => {
    expect(attributeName("col:active")).toBeNull();
    expect(attributeName("fn:abs:attr:5:rank")).toBeNull();
  });
});
