import { expect, it } from "vitest";
import { noteWithNumber } from "./ModelEditor";

const rule = (d: number) => ({ id: "c_apart", left: { var: "x", index: [] }, relation: "<=", right: { const: d } });

it("brings a note's number up to date when the rule's one number changes (benchmark re-test, October 2026)", () => {
  expect(noteWithNumber("chosen sites at least 10000 apart", rule(10000), rule(5))).toBe("chosen sites at least 5 apart");
  expect(noteWithNumber("at most 10,000 m", rule(10000), rule(12000))).toBe("at most 12,000 m");
  // A note that does not say the number, or two numbers changed: left for the person.
  expect(noteWithNumber("sites far apart", rule(10000), rule(5))).toBeNull();
  expect(noteWithNumber("10000 and 3", { a: { const: 10000 }, b: { const: 3 } }, { a: { const: 5 }, b: { const: 4 } })).toBeNull();
  // 100 is not the 100 inside 1000.
  expect(noteWithNumber("at most 1000", rule(100), rule(50))).toBeNull();
});

it("follows one distance held three times, as D, D and -D (benchmark round 3)", () => {
  const apart = (d: number) => ({ left: { add: [{ mul: [{ const: d }, { var: "open" }] }, { mul: [{ const: d }, { var: "open" }] }, { const: -d }] },
    right: { par: "dist" } });
  expect(noteWithNumber("two chosen base items are at least 10000 apart in dist (change 10000 to the distance wanted)", apart(10000), apart(8)))
    .toBe("two chosen base items are at least 8 apart in dist (change 8 to the distance wanted)");
});
