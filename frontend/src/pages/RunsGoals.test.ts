import { expect, it } from "vitest";
import { goalChanges } from "./Runs";

it("compares every goal, not only the first, when goals are in order (benchmark re-test, October 2026)", () => {
  const a = { objective_mode: "lex", objective_terms: [{ id: "covered", value: 2588 }, { id: "response_time", value: 2179.2 }] };
  const b = { objective_mode: "lex", objective_terms: [{ id: "covered", value: 2588 }, { id: "response_time", value: 4323 }] };
  expect(goalChanges(a, b)).toEqual([{ id: "covered", left: 2588, right: 2588 }, { id: "response_time", left: 2179.2, right: 4323 }]);
  // The breakdown (every run since G5a) is read first; one goal alone needs no list.
  expect(goalChanges({ objective_breakdown: { terms: [{ id: "cost", value: 3 }] } }, {})).toEqual([]);
});
