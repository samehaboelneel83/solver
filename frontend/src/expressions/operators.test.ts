import { describe, expect, it } from "vitest";
import { DATA_TYPES } from "../components/attrTypes";
import type { AttrType } from "../api/v1";
import {
  EXPRESSION_OPERATORS,
  NULL_OPERATORS,
  OPERATORS_BY_TYPE,
  operatorsForField,
} from "./operators";
import { buildFieldCatalogue, encodeFieldId } from "./fields";
import { ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * Operators are a table keyed by data type, not one list for everything
 * and not a `switch` in a component: "is greater than" is meaningless on a
 * boolean, and "starts with" is meaningless on an integer, and the thing
 * that knows which is which has to be one thing.
 */

const catalogue = buildFieldCatalogue({
  entityTypes: ENTITY_TYPES,
  relationshipTypes: RELATIONSHIP_TYPES,
});

function attributeField(entityTypeId: string, attribute: string) {
  const field = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId, attribute }));
  if (!field) throw new Error(`fixture missing: ${entityTypeId}.${attribute}`);
  return field;
}

function names(field: Parameters<typeof operatorsForField>[0]): string[] {
  return operatorsForField(field).map((o) => o.name);
}

describe("the operator table", () => {
  it("covers every v1 data type", () => {
    for (const { value } of DATA_TYPES) {
      expect(OPERATORS_BY_TYPE[value], value).toBeDefined();
      expect(OPERATORS_BY_TYPE[value].length, value).toBeGreaterThan(0);
    }
  });

  it("only ever names operators the table defines", () => {
    const lists: readonly (readonly string[])[] = [...Object.values(OPERATORS_BY_TYPE), NULL_OPERATORS];
    for (const list of lists) {
      for (const name of list) {
        expect(EXPRESSION_OPERATORS[name], name).toBeDefined();
      }
    }
  });

  it("gives ordering operators to the ordered types and to nothing else", () => {
    const ordered: AttrType[] = ["integer", "number", "date", "time"];
    const unordered: AttrType[] = ["text", "boolean", "enum"];
    for (const type of ordered) {
      expect(OPERATORS_BY_TYPE[type], type).toEqual(expect.arrayContaining(["<", "<=", ">", ">="]));
    }
    for (const type of unordered) {
      for (const op of ["<", "<=", ">", ">="]) {
        expect(OPERATORS_BY_TYPE[type], `${type} ${op}`).not.toContain(op);
      }
    }
  });

  it("gives substring operators to text and to nothing else", () => {
    expect(OPERATORS_BY_TYPE.text).toEqual(
      expect.arrayContaining(["contains", "beginsWith", "endsWith", "doesNotContain"])
    );
    for (const { value } of DATA_TYPES) {
      if (value === "text") continue;
      expect(OPERATORS_BY_TYPE[value], value).not.toContain("contains");
    }
  });

  it("gives boolean equality only", () => {
    expect([...OPERATORS_BY_TYPE.boolean].sort()).toEqual(["!=", "="]);
  });

  it("gives enum membership as well as equality", () => {
    expect(OPERATORS_BY_TYPE.enum).toEqual(expect.arrayContaining(["in", "notIn", "=", "!="]));
  });

  it("declares the arity each operator's value has to satisfy", () => {
    expect(EXPRESSION_OPERATORS["null"].arity).toBe("unary");
    expect(EXPRESSION_OPERATORS["notNull"].arity).toBe("unary");
    expect(EXPRESSION_OPERATORS["in"].arity).toBe("list");
    expect(EXPRESSION_OPERATORS["notIn"].arity).toBe("list");
    expect(EXPRESSION_OPERATORS["="].arity).toBe("binary");
    expect(EXPRESSION_OPERATORS["contains"].arity).toBe("binary");
  });

  it("labels every operator in words rather than in symbols", () => {
    for (const [name, def] of Object.entries(EXPRESSION_OPERATORS)) {
      expect(def.label, name).toBeTruthy();
      expect(def.label, name).toMatch(/[a-z]/);
    }
  });
});

describe("operatorsForField", () => {
  it("adds the null operators to an optional field and withholds them from a required one", () => {
    expect(names(attributeField("1", "grade"))).toEqual(expect.arrayContaining([...NULL_OPERATORS]));
    // `capacity` is required on `unit`, so the trigger guarantees it is
    // present -- "is empty" would be dead UI.
    for (const op of NULL_OPERATORS) {
      expect(names(attributeField("1", "capacity")), op).not.toContain(op);
    }
  });

  it("offers the operators of the field's own data type", () => {
    expect(names(attributeField("1", "capacity"))).toEqual(expect.arrayContaining([">", "<"]));
    expect(names(attributeField("1", "code"))).toEqual(expect.arrayContaining(["contains"]));
    expect(names(attributeField("1", "code"))).not.toContain(">");
  });

  it("offers a function field the operators of its RETURN type", () => {
    // `year(opened)` is an integer, so it is ordered, even though its
    // argument is a date and `lower(code)` beside it is not.
    const year = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "year",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "opened" },
      })
    )!;
    expect(names(year)).toEqual(expect.arrayContaining([">", "<", "="]));
    expect(names(year)).not.toContain("contains");

    const lower = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "lower",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "code" },
      })
    )!;
    expect(names(lower)).toContain("contains");
    expect(names(lower)).not.toContain(">");
  });

  it("never offers null operators on a relationship count, which is always a number", () => {
    const count = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "count",
        argument: { kind: "relationship", relationshipTypeId: "10", direction: "outgoing" },
      })
    )!;
    expect(names(count)).toEqual(expect.arrayContaining([">", "="]));
    for (const op of NULL_OPERATORS) {
      expect(names(count), op).not.toContain(op);
    }
  });
});
