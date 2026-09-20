import { describe, expect, it } from "vitest";
import {
  ENTITY_COLUMNS,
  buildFieldCatalogue,
  decodeFieldId,
  encodeFieldId,
} from "./fields";
import { ENTITY_TYPES, RELATIONSHIP_TYPES, SHIFT_TYPE, UNIT_TYPE } from "./testFixtures";

/**
 * The field catalogue is the half of the format Task 14d has to agree with
 * character for character: a document stores a field as ONE string, and
 * both this client and that server have to read the same thing out of it.
 * So the tests here are about identity and round-tripping, not about
 * whether a list happens to contain a name.
 */

describe("field ids", () => {
  it("round-trips every reference kind", () => {
    const refs = [
      { kind: "column", column: "key" },
      { kind: "attribute", entityTypeId: "1", attribute: "capacity" },
      { kind: "function", fn: "year", argument: { kind: "attribute", entityTypeId: "1", attribute: "opened" } },
      { kind: "function", fn: "lower", argument: { kind: "column", column: "label" } },
      {
        kind: "function",
        fn: "count",
        argument: { kind: "relationship", relationshipTypeId: "10", direction: "outgoing" },
      },
    ] as const;
    for (const ref of refs) {
      const id = encodeFieldId(ref);
      expect(decodeFieldId(id), id).toEqual(ref);
    }
  });

  it("gives a column and a same-named attribute different ids", () => {
    // Task 12: an entity type may legally declare an attribute called
    // `key`, `label`, `sort_order` or `active`. A bare name cannot say
    // which one a rule means.
    const column = encodeFieldId({ kind: "column", column: "key" });
    const attribute = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "key" });
    expect(column).not.toBe(attribute);
  });

  it("gives the same attribute name on two entity types different ids", () => {
    const onUnit = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" });
    const onShift = encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" });
    expect(onUnit).not.toBe(onShift);
  });

  it("refuses ids it cannot read", () => {
    for (const bad of [
      "",
      "capacity",
      "col:",
      "col:nonsense",
      "attr:1",
      "attr:x:capacity",
      "fn:year",
      "rel:10:outgoing", // a relationship is only ever a function ARGUMENT
      "rel:10:sideways",
      "wat:1:2",
    ]) {
      expect(decodeFieldId(bad), bad).toBeNull();
    }
  });

  it("refuses a direction count() does not have", () => {
    // Only reachable through a call: a bare `rel:` id is refused for a
    // different reason, so testing it there proves nothing about the
    // direction vocabulary. (Found by a surviving mutant.)
    expect(decodeFieldId("fn:count:rel:10:sideways")).toBeNull();
    expect(decodeFieldId("fn:count:rel:10:incoming")).not.toBeNull();
  });

  it("refuses a nested function rather than reading it as a flat one", () => {
    // `abs(year(opened))` is not expressible in version 1, and the decoder
    // must say so by refusing rather than silently dropping a level.
    expect(decodeFieldId("fn:abs:fn:year:attr:1:opened")).toBeNull();
  });
});

describe("buildFieldCatalogue", () => {
  const catalogue = buildFieldCatalogue({
    entityTypes: ENTITY_TYPES,
    relationshipTypes: RELATIONSHIP_TYPES,
  });

  it("carries each attribute with the data type its definition declares", () => {
    const unitCapacity = catalogue.get(
      encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" })
    );
    const shiftCapacity = catalogue.get(
      encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" })
    );
    expect(unitCapacity?.dataType).toBe("integer");
    expect(shiftCapacity?.dataType).toBe("number");
  });

  it("carries an enum attribute's own values, and nothing else's", () => {
    const band = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "band" }));
    expect(band?.enumValues).toEqual(["low", "high"]);
    const code = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "code" }));
    expect(code?.enumValues).toBeNull();
  });

  it("marks a required attribute not nullable and an optional one nullable", () => {
    const capacity = catalogue.get(
      encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" })
    );
    const grade = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "grade" }));
    expect(capacity?.nullable).toBe(false);
    expect(grade?.nullable).toBe(true);
  });

  it("groups fields by the entity type they belong to", () => {
    const capacity = catalogue.get(
      encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" })
    );
    expect(capacity?.group).toBe(SHIFT_TYPE.name);
  });

  it("says so in the label when an attribute shadows an entity column", () => {
    // `key` and `active` are columns; `unit` also declares attributes with
    // those names. The group alone does not disambiguate for a reader who
    // is scanning labels, so the label does.
    const key = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "key" }));
    const code = catalogue.get(encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "code" }));
    expect(key?.label).toContain("attribute");
    expect(code?.label).not.toContain("attribute");
  });

  it("offers the entity columns asked for, and only those", () => {
    const all = buildFieldCatalogue({ entityTypes: ENTITY_TYPES });
    for (const column of ENTITY_COLUMNS) {
      expect(all.get(encodeFieldId({ kind: "column", column: column.column })), column.column).toBeDefined();
    }
    const narrowed = buildFieldCatalogue({ entityTypes: ENTITY_TYPES, columns: ["label"] });
    expect(narrowed.get(encodeFieldId({ kind: "column", column: "label" }))).toBeDefined();
    expect(narrowed.get(encodeFieldId({ kind: "column", column: "key" }))).toBeUndefined();

    const none = buildFieldCatalogue({ entityTypes: ENTITY_TYPES, columns: [] });
    for (const column of ENTITY_COLUMNS) {
      expect(none.get(encodeFieldId({ kind: "column", column: column.column })), column.column).toBeUndefined();
    }
  });

  it("offers each function only over arguments whose type it accepts", () => {
    // `year` takes a date. `opened` is one; `code` (text) and `capacity`
    // (integer) are not -- and neither is a text attribute whose VALUES
    // might look like years, which is why the check is on the declared
    // data type, never on a value.
    expect(
      catalogue.get(
        encodeFieldId({
          kind: "function",
          fn: "year",
          argument: { kind: "attribute", entityTypeId: "1", attribute: "opened" },
        })
      )
    ).toBeDefined();
    for (const attribute of ["code", "capacity", "starts", "band"]) {
      expect(
        catalogue.get(
          encodeFieldId({
            kind: "function",
            fn: "year",
            argument: { kind: "attribute", entityTypeId: "1", attribute },
          })
        ),
        attribute
      ).toBeUndefined();
    }
  });

  it("gives a function field the function's return type, not its argument's", () => {
    const year = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "year",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "opened" },
      })
    );
    expect(year?.dataType).toBe("integer");
    const lower = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "lower",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "code" },
      })
    );
    expect(lower?.dataType).toBe("text");
  });

  it("keeps abs's return type in step with its argument's", () => {
    const onInteger = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "abs",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "capacity" },
      })
    );
    const onNumber = catalogue.get(
      encodeFieldId({
        kind: "function",
        fn: "abs",
        argument: { kind: "attribute", entityTypeId: "1", attribute: "grade" },
      })
    );
    expect(onInteger?.dataType).toBe("integer");
    expect(onNumber?.dataType).toBe("number");
  });

  it("offers count over each relationship type in each direction", () => {
    for (const direction of ["outgoing", "incoming", "any"] as const) {
      const field = catalogue.get(
        encodeFieldId({
          kind: "function",
          fn: "count",
          argument: { kind: "relationship", relationshipTypeId: "10", direction },
        })
      );
      expect(field, direction).toBeDefined();
      expect(field?.dataType).toBe("integer");
      expect(field?.nullable).toBe(false);
    }
  });

  it("offers no relationship counts when it is given no relationship types", () => {
    const without = buildFieldCatalogue({ entityTypes: ENTITY_TYPES });
    expect(without.fields.some((f) => f.ref.kind === "function" && f.ref.fn === "count")).toBe(false);
    expect(catalogue.fields.some((f) => f.ref.kind === "function" && f.ref.fn === "count")).toBe(true);
  });

  it("has no duplicate ids", () => {
    const ids = catalogue.fields.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("orders fields by group then label, so the picker is scannable", () => {
    const labels = catalogue.fields
      .filter((f) => f.group === UNIT_TYPE.name)
      .map((f) => f.label);
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b)));
  });
});
