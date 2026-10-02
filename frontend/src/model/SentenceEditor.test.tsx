import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { RuleWords } from "./SentenceEditor";
import { renameIndex } from "./renameIndex";
import type { Constraint, ModelContext } from "./terms";

const RULE = {
  id: "city_served",
  forall: [{ index: "v", set: "city" }],
  left: { sum: { mul: [{ par: "reach", index: ["v", "b"] }, { var: "open", index: ["b"] }] }, over: [{ index: "b", set: "base" }] },
  relation: ">=",
  right: { attr: { of: "v", name: "need" } },
  severity: "hard",
} as unknown as Constraint;

it("follows a renamed item everywhere it is read, but not under a total that names its own", () => {
  expect(renameIndex(RULE.left, "v", "c")).toEqual({
    sum: { mul: [{ par: "reach", index: ["c", "b"] }, { var: "open", index: ["b"] }] }, over: [{ index: "b", set: "base" }],
  });
  expect(renameIndex({ attr: { of: "v", name: "need" } }, "v", "c")).toEqual({ attr: { of: "c", name: "need" } });
  expect(renameIndex({ via: { rel: "base_of", from: "v" } }, "v", "c")).toEqual({ via: { rel: "base_of", from: "c" } });
  const shadowed = { sum: { var: "x", index: ["b"] }, over: [{ index: "b", set: "base" }] };
  expect(renameIndex(shadowed, "b", "z")).toBe(shadowed);
});

it("renames a rule's references when its 'for each' name is changed", () => {
  const context: ModelContext = { sets: ["city", "base"], setIds: {}, relationships: [],
    variables: { open: { index: ["base"], domain: "binary" } }, parameters: { reach: { index: ["city", "base"] } },
    attributes: { city: [{ name: "need", data_type: "number" }], base: [] } };
  let latest = RULE;
  function Harness() {
    const [rule, setRule] = useState(RULE);
    return <RuleWords rule={rule} context={context} onChange={(next) => { latest = next; setRule(next); }} />;
  }
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("for each: name 1"), { target: { value: "c" } });
  expect(latest.forall).toEqual([{ index: "c", set: "city" }]);
  expect(JSON.stringify(latest.left)).toContain('"index":["c","b"]');
  expect(latest.right).toEqual({ attr: { of: "c", name: "need" } });
});
