import { describe, expect, it } from "vitest";
import { DATA_TYPES } from "../components/attrTypes";
import { EXPRESSION_FUNCTIONS, FUNCTION_NAMES, functionReturnType } from "./functions";

/**
 * The function catalogue is the part of this task that Task 14d has to
 * compile to SQL. A function that exists here and not there is a promise
 * the product cannot keep, so the catalogue is deliberately closed, every
 * entry carries the SQL it becomes, and the tests below are about the
 * DECLARED types -- never about whether a particular value happens to
 * parse. `"2026"` is a perfectly good text and a perfectly good year, so a
 * test that fed it in would prove nothing at all.
 */

describe("the function catalogue", () => {
  it("is closed: the exported names and the table are the same set", () => {
    expect([...FUNCTION_NAMES].sort()).toEqual(Object.keys(EXPRESSION_FUNCTIONS).sort());
  });

  it("ships exactly the entries Task 14d has agreed to compile", () => {
    expect([...FUNCTION_NAMES].sort()).toEqual(
      ["abs", "count", "day", "hour", "length", "lower", "minute", "month", "upper", "year"].sort()
    );
  });

  it("gives every entry a SQL template, so nothing can be added here without one", () => {
    for (const name of FUNCTION_NAMES) {
      const def = EXPRESSION_FUNCTIONS[name];
      expect(def.sql, name).toBeTruthy();
      // A field function's template must consume its argument; `count`'s
      // consumes the relationship type and the direction instead.
      if (def.argument === "field") {
        expect(def.sql, name).toContain("{arg}");
      } else {
        expect(def.sql, name).toContain(":relationship_type_id");
      }
    }
  });

  it("names every argument type from the v1 data-type vocabulary", () => {
    const known = new Set(DATA_TYPES.map((t) => t.value));
    for (const name of FUNCTION_NAMES) {
      const def = EXPRESSION_FUNCTIONS[name];
      for (const type of def.argumentTypes) {
        expect(known.has(type), `${name}(${type})`).toBe(true);
      }
      if (def.returns !== "argument") {
        expect(known.has(def.returns), `${name} returns ${def.returns}`).toBe(true);
      }
    }
  });

  it("takes only the argument types each function is defined on", () => {
    // Stated as a table rather than as prose, because this is the thing the
    // validator enforces and the catalogue builder filters by.
    const expected: Record<string, string[]> = {
      year: ["date"],
      month: ["date"],
      day: ["date"],
      hour: ["time"],
      minute: ["time"],
      lower: ["text"],
      upper: ["text"],
      length: ["text"],
      abs: ["integer", "number"],
      count: [],
    };
    for (const [name, types] of Object.entries(expected)) {
      expect([...EXPRESSION_FUNCTIONS[name].argumentTypes].sort(), name).toEqual([...types].sort());
    }
  });

  it("makes count the only entry that takes a relationship rather than a field", () => {
    const relational = FUNCTION_NAMES.filter((n) => EXPRESSION_FUNCTIONS[n].argument === "relationship");
    expect(relational).toEqual(["count"]);
  });
});

describe("functionReturnType", () => {
  it("returns the declared type for a fixed-return function", () => {
    expect(functionReturnType(EXPRESSION_FUNCTIONS.year, "date")).toBe("integer");
    expect(functionReturnType(EXPRESSION_FUNCTIONS.hour, "time")).toBe("integer");
    expect(functionReturnType(EXPRESSION_FUNCTIONS.length, "text")).toBe("integer");
    expect(functionReturnType(EXPRESSION_FUNCTIONS.lower, "text")).toBe("text");
    expect(functionReturnType(EXPRESSION_FUNCTIONS.count, null)).toBe("integer");
  });

  it("follows the argument for abs, so an integer stays an integer", () => {
    // The distinction is load-bearing: it decides whether the value editor
    // refuses `2.5`, and whether 14d casts to integer or to numeric.
    expect(functionReturnType(EXPRESSION_FUNCTIONS.abs, "integer")).toBe("integer");
    expect(functionReturnType(EXPRESSION_FUNCTIONS.abs, "number")).toBe("number");
  });
});
