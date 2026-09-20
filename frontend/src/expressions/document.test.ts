import { describe, expect, it } from "vitest";
import type { RuleGroupType } from "react-querybuilder";
import {
  EXPRESSION_VERSION,
  countRules,
  emptyDocument,
  isEmptyDocument,
  toDocument,
  toQuery,
} from "./document";

/**
 * One module owns the wire shape, because Task 14d sends this same
 * document to the server and compiles it there. The two things that matter
 * are that the version travels from day one, and that what we store is
 * react-querybuilder's own `RuleGroupType` -- a documented subset of it --
 * rather than a second, parallel format that would have to be kept in step
 * with it by hand.
 */

describe("the expression document", () => {
  it("carries a version from day one", () => {
    expect(emptyDocument().version).toBe(EXPRESSION_VERSION);
    expect(EXPRESSION_VERSION).toBe(1);
  });

  it("starts as an and-group with no rules", () => {
    expect(emptyDocument().query).toEqual({ combinator: "and", rules: [] });
  });

  it("survives JSON, which is how it reaches Task 14d", () => {
    const doc = toDocument({
      combinator: "or",
      rules: [
        { field: "attr:1:capacity", operator: ">", value: 3 },
        { combinator: "and", not: true, rules: [{ field: "attr:1:code", operator: "contains", value: "ab" }] },
      ],
    });
    expect(JSON.parse(JSON.stringify(doc))).toEqual(doc);
  });
});

describe("toDocument", () => {
  it("drops react-querybuilder's in-memory bookkeeping", () => {
    // `id` and `path` are regenerated on every mount; storing them would
    // make two identical expressions compare unequal and would send noise
    // over the wire.
    const query = {
      id: "g1",
      path: [],
      combinator: "and",
      rules: [{ id: "r1", path: [0], field: "attr:1:capacity", operator: "=", value: 1 }],
    } as unknown as RuleGroupType;
    expect(toDocument(query)).toEqual({
      version: EXPRESSION_VERSION,
      query: { combinator: "and", rules: [{ field: "attr:1:capacity", operator: "=", value: 1 }] },
    });
  });

  it("keeps `not`, which negates a whole group", () => {
    const doc = toDocument({ combinator: "and", not: true, rules: [] } as RuleGroupType);
    expect(doc.query.not).toBe(true);
    // ...and leaves it off when it is false, so an untouched document has
    // no redundant keys.
    expect(toDocument({ combinator: "and", not: false, rules: [] } as RuleGroupType).query.not).toBeUndefined();
  });

  it("keeps the JSON type of every value", () => {
    const doc = toDocument({
      combinator: "and",
      rules: [
        { field: "a", operator: "=", value: 3 },
        { field: "b", operator: "=", value: true },
        { field: "c", operator: "=", value: "3" },
        { field: "d", operator: "in", value: ["x", "y"] },
      ],
    } as RuleGroupType);
    const values = (doc.query.rules as { value: unknown }[]).map((r) => r.value);
    expect(values).toEqual([3, true, "3", ["x", "y"]]);
    expect(typeof values[0]).toBe("number");
    expect(typeof values[2]).toBe("string");
  });

  it("drops the value of a unary operator, which has none", () => {
    const doc = toDocument({
      combinator: "and",
      rules: [{ field: "a", operator: "null", value: "left over from the last operator" }],
    } as RuleGroupType);
    expect(doc.query.rules[0]).toEqual({ field: "a", operator: "null", value: null });
  });

  it("recurses into nested groups", () => {
    const doc = toDocument({
      combinator: "and",
      rules: [
        {
          id: "g2",
          combinator: "or",
          rules: [{ id: "r2", field: "a", operator: "=", value: 1 }],
        },
      ],
    } as unknown as RuleGroupType);
    expect(JSON.stringify(doc)).not.toContain("g2");
    expect(JSON.stringify(doc)).not.toContain("r2");
  });
});

describe("toQuery", () => {
  it("round-trips a document back into something the builder can render", () => {
    const doc = toDocument({
      combinator: "or",
      rules: [{ field: "a", operator: "=", value: 1 }],
    } as RuleGroupType);
    expect(toDocument(toQuery(doc))).toEqual(doc);
  });
});

describe("isEmptyDocument", () => {
  it("is true for a document with no rules anywhere, and false as soon as there is one", () => {
    expect(isEmptyDocument(emptyDocument())).toBe(true);
    expect(
      isEmptyDocument(toDocument({ combinator: "and", rules: [{ combinator: "or", rules: [] }] } as RuleGroupType))
    ).toBe(true);
    expect(
      isEmptyDocument(
        toDocument({
          combinator: "and",
          rules: [{ combinator: "or", rules: [{ field: "a", operator: "=", value: 1 }] }],
        } as RuleGroupType)
      )
    ).toBe(false);
  });

  it("is true for null, which is how a consumer says there is no expression", () => {
    expect(isEmptyDocument(null)).toBe(true);
  });
});

describe("countRules", () => {
  it("counts rules at every depth and ignores the groups themselves", () => {
    const doc = toDocument({
      combinator: "and",
      rules: [
        { field: "a", operator: "=", value: 1 },
        {
          combinator: "or",
          rules: [
            { field: "b", operator: "=", value: 2 },
            { combinator: "and", rules: [{ field: "c", operator: "=", value: 3 }] },
          ],
        },
      ],
    } as RuleGroupType);
    expect(countRules(doc)).toBe(3);
  });
});
