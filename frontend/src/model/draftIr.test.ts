import { describe, expect, it } from "vitest";
import { formDraftOf, publishable, withFormDraft } from "./draftIr";

const IR = {
  version: 1, sets: ["cell", "zone"], relationships: ["adjacent"], parameters: {},
  variables: { assign: { index: ["cell", "zone"], domain: "binary" } },
  constraints: [{ id: "c", note: "  ", connected: { assign: { var: "assign", index: ["u", "z"] }, units: { index: "u", set: "cell" }, groups: { index: "z", set: "zone" }, via: "adjacent" }, severity: "hard", weight: 3 }],
};

describe("the form projection of a draft", () => {
  it("keeps every key the forms do not show, relationships included", () => {
    const draft = formDraftOf(IR);
    const back = withFormDraft({ ...IR, extra: { kept: true } }, { ...draft, sets: ["cell", "zone", "day"] });
    expect(back.relationships).toEqual(["adjacent"]);
    expect(back.extra).toEqual({ kept: true });
    expect(back.sets).toEqual(["cell", "zone", "day"]);
  });

  it("publishes what the forms always published: current version, walked relationships, no blank note, no hard weight", () => {
    const out = publishable(IR);
    expect(out.version).toBe(2);
    expect(out.relationships).toEqual(["adjacent"]);
    expect((out.constraints as Record<string, unknown>[])[0]).not.toHaveProperty("note");
    expect((out.constraints as Record<string, unknown>[])[0]).not.toHaveProperty("weight");
  });
});

it("leaves out a rule still as a blank rule starts, 0 <= 0 (benchmark round 3)", () => {
  const ir = { version: 2, sets: ["day"], parameters: {}, variables: { x: { index: ["day"], domain: "binary" } },
    constraints: [
      { id: "c_1", forall: [{ index: "d", set: "day" }], left: { const: 0 }, relation: "<=", right: { const: 0 }, severity: "hard" },
      { id: "c_real", left: { var: "x", index: ["d"] }, relation: "<=", right: { const: 1 }, severity: "hard",
        forall: [{ index: "d", set: "day" }] },
    ],
    objective: { sense: "minimize", mode: "weighted", terms: [] } };
  expect((publishable(ir).constraints as { id: string }[]).map((c) => c.id)).toEqual(["c_real"]);
});
