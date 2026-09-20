import { describe, expect, it } from "vitest";
import { buildFieldCatalogue, COLUMN_GROUP } from "./fields";
import {
  defaultFieldId,
  defaultRule,
  defaultValueFor,
  isUntouchedRule,
  withoutUntouchedRules,
} from "./defaults";
import { EXPRESSION_VERSION, type ExpressionDocument } from "./document";
import { UNIT_TYPE, ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * What "+ Condition" creates, and why the filter ignores it until it is
 * touched. See `defaults.ts` for the reasoning; these pin the two claims
 * that are easy to break -- that the default field is not a generated call,
 * and that an untouched rule is removed from what is sent but from nothing
 * else.
 */

const full = buildFieldCatalogue({ entityTypes: ENTITY_TYPES, relationshipTypes: RELATIONSHIP_TYPES });
const graphLike = buildFieldCatalogue({
  entityTypes: ENTITY_TYPES,
  relationshipTypes: RELATIONSHIP_TYPES,
  columns: [],
});

describe("defaultFieldId", () => {
  it("is one of the entity's own columns when the consumer has them", () => {
    const id = defaultFieldId(full) as string;
    expect(full.get(id)?.group).toBe(COLUMN_GROUP);
    expect(id).toBe("col:key");
  });

  it("is never a generated call", () => {
    // The defect: `catalogue.fields[0]` is alphabetically first by group
    // then LABEL, and a call sorts under its own name -- so the first
    // field of this very catalogue is `abs(capacity)`, which is what a new
    // condition used to start on.
    expect(full.fields[0].ref.kind).toBe("function");
    expect(full.fields[0].label.startsWith("abs(")).toBe(true);
    expect(full.get(defaultFieldId(full) as string)?.ref.kind).not.toBe("function");
    expect(graphLike.get(defaultFieldId(graphLike) as string)?.ref.kind).not.toBe("function");
  });

  it("falls back to a plain attribute when the consumer offers no columns", () => {
    // The graph's catalogue (`graphFilter.ts`) carries no entity columns.
    const id = defaultFieldId(graphLike) as string;
    expect(graphLike.get(id)?.ref.kind).toBe("attribute");
  });

  it("is undefined for a catalogue with nothing in it", () => {
    expect(defaultFieldId(buildFieldCatalogue({ entityTypes: [], columns: [] }))).toBeUndefined();
  });
});

describe("defaultRule", () => {
  it("is a complete rule, so the builder can render the row", () => {
    expect(defaultRule(full)).toStrictEqual({ field: "col:key", operator: "=", value: "" });
  });

  it("is null when there is no field to build one from", () => {
    expect(defaultRule(buildFieldCatalogue({ entityTypes: [], columns: [] }))).toBeNull();
  });
});

describe("isUntouchedRule", () => {
  const untouched = { field: "col:key", operator: "=", value: "" };

  it("is true for the rule the button creates", () => {
    expect(isUntouchedRule(untouched, full)).toBe(true);
  });

  it("is false once the field changed", () => {
    expect(isUntouchedRule({ ...untouched, field: `attr:${UNIT_TYPE.id}:capacity` }, full)).toBe(false);
  });

  it("is false once the operator changed, even with the value still empty", () => {
    // `key contains ""` matches everything, but the person has said
    // something about this condition, so it is theirs to own.
    expect(isUntouchedRule({ ...untouched, operator: "contains" }, full)).toBe(false);
  });

  it("is false once the value changed", () => {
    expect(isUntouchedRule({ ...untouched, value: "a" }, full)).toBe(false);
  });

  it("compares a list value by its contents, not by reference", () => {
    const listCatalogue = buildFieldCatalogue({ entityTypes: [UNIT_TYPE], columns: [] });
    const rule = defaultRule(listCatalogue);
    expect(rule && isUntouchedRule({ ...rule, value: structuredClone(rule.value) }, listCatalogue)).toBe(
      true
    );
  });

  it("is false for every rule when the catalogue offers no default at all", () => {
    const empty = buildFieldCatalogue({ entityTypes: [], columns: [] });
    expect(isUntouchedRule(untouched, empty)).toBe(false);
  });
});

describe("withoutUntouchedRules", () => {
  const doc = (rules: unknown[]): ExpressionDocument =>
    ({ version: EXPRESSION_VERSION, query: { combinator: "and", rules } }) as ExpressionDocument;

  it("removes a rule nobody has touched", () => {
    const pruned = withoutUntouchedRules(doc([{ field: "col:key", operator: "=", value: "" }]), full);
    expect(pruned?.query.rules).toEqual([]);
  });

  it("keeps a rule the person has filled in, and removes only the new one beside it", () => {
    const real = { field: "col:key", operator: "contains", value: "ahm" };
    const pruned = withoutUntouchedRules(
      doc([real, { field: "col:key", operator: "=", value: "" }]),
      full
    );
    expect(pruned?.query.rules).toEqual([real]);
  });

  it("reaches into nested groups and keeps their combinator and negation", () => {
    const real = { field: "col:key", operator: "contains", value: "ahm" };
    const pruned = withoutUntouchedRules(
      doc([
        { combinator: "or", not: true, rules: [real, { field: "col:key", operator: "=", value: "" }] },
      ]),
      full
    );
    expect(pruned?.query.rules).toEqual([{ combinator: "or", not: true, rules: [real] }]);
  });

  it("keeps a group that pruning emptied rather than deleting it", () => {
    // `isEmptyDocument` already reads a group with no rules as "no
    // constraint", and removing the group would change what a rule the
    // person adds next is combined with.
    const pruned = withoutUntouchedRules(
      doc([{ combinator: "or", rules: [{ field: "col:key", operator: "=", value: "" }] }]),
      full
    );
    expect(pruned?.query.rules).toEqual([{ combinator: "or", rules: [] }]);
  });

  it("passes null through", () => {
    expect(withoutUntouchedRules(null, full)).toBeNull();
  });

  it("does not mutate the document it was given", () => {
    const original = doc([{ field: "col:key", operator: "=", value: "" }]);
    withoutUntouchedRules(original, full);
    expect(original.query.rules).toHaveLength(1);
  });
});

describe("defaultValueFor", () => {
  // It moved here from ExpressionBuilder.tsx; the builder re-exports it and
  // ExpressionBuilder.test.tsx still covers the per-type branches. This is
  // the one thing that changed: the default field it is called with.
  it("gives a text field an empty string, so a new condition shows no error", () => {
    expect(defaultValueFor(full.get("col:key"), "=")).toBe("");
  });
});
