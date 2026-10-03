import { describe, expect, it } from "vitest";
import { checkWhere } from "./blockCheck";
import type { ModelContext } from "./terms";

const context = {
  sets: ["intersection"], setIds: {}, variables: {}, parameters: {}, relationships: [],
  attributes: { intersection: [{ name: "signalized", data_type: "boolean" }, { name: "lanes", data_type: "integer" }] },
} as ModelContext;

describe("conditions on a record's fields", () => {
  it("says a yes/no field is compared with true or false, not a text (benchmark round 5)", () => {
    expect(checkWhere({ index: "j", set: "intersection", where: [{ attr: "signalized", op: "=", value: "Y" }] }, context))
      .toEqual(["signalized is yes or no, so compare it with true or false (not “Y”)"]);
    expect(checkWhere({ index: "j", set: "intersection", where: [{ attr: "signalized", op: "=", value: true }] }, context)).toEqual([]);
  });
});
