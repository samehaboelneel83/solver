import { describe, expect, it } from "vitest";
import { fieldsRead } from "./fieldsRead";

describe("the record fields a model reads", () => {
  it("finds fields in rules and goals, each named by the set its own rule binds (UX audit B-7)", () => {
    const model = {
      constraints: [
        { id: "c_capacity", forall: [{ index: "r", set: "room" }, { index: "s", set: "section" }],
          left: { mul: [{ attr: { of: "s", name: "enrollment" } }, { var: "assign", index: ["s", "r"] }] },
          relation: "<=", right: { attr: { of: "r", name: "capacity" } } },
        // The same letter bound to another set in another rule.
        { id: "c_other", forall: [{ index: "s", set: "slot" }], left: { attr: { of: "s", name: "late" } }, relation: "<=", right: { const: 1 } },
        { id: "c_walk", forall: [{ index: "m", set: "employee" }],
          left: { sum: { attr: { of: "w", name: "share" } }, over: [{ index: "e", set: "employee", via: { rel: "manages", from: "m", as: "w" } }] },
          relation: "<=", right: { const: 1 } },
      ],
      objective: { terms: [{ id: "o", expression: { sum: { attr: { of: "t", name: "cost" } }, over: [{ index: "t", set: "slot" }] } }] },
    };
    expect(fieldsRead(model)).toEqual([
      { set: "manages", name: "share", link: true },
      { set: "room", name: "capacity" },
      { set: "section", name: "enrollment" },
      { set: "slot", name: "cost" },
      { set: "slot", name: "late" },
    ]);
  });
});
