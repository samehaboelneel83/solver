import { describe, expect, it } from "vitest";
import {
  parameterIsUsable,
  parameterOptions,
  referencesOf,
  strandedBy,
  variableNameProblem,
  withDomain,
  cleanVariable,
} from "./declarations";
import type { Constraint, ObjectiveTerm, Term } from "./terms";

const ENTITY_TYPES = [
  { id: 5, name: "employee" },
  { id: 6, name: "day" },
  { id: 7, name: "shift" },
];

describe("parameterOptions", () => {
  it("reads a parameter's index back as set names, in order", () => {
    // `demand[day, shift]` is not `demand[shift, day]`: getting this backwards
    // type-checks by arity and quietly means a different model.
    const options = parameterOptions(
      [{ id: 1, name: "demand", index_type_ids: [6, 7] }],
      ENTITY_TYPES
    );

    expect(options).toEqual([{ name: "demand", index: ["day", "shift"] }]);
  });

  it("leaves a position blank when the type is unknown rather than guessing", () => {
    const options = parameterOptions(
      [{ id: 1, name: "demand", index_type_ids: [6, 999] }],
      ENTITY_TYPES
    );

    expect(options[0].index).toEqual(["day", ""]);
  });
});

describe("parameterIsUsable", () => {
  it("accepts a parameter whose every index position is a declared set", () => {
    expect(parameterIsUsable({ name: "demand", index: ["day", "shift"] }, ["day", "shift"])).toEqual({
      usable: true,
    });
  });

  it("names the sets that are missing", () => {
    const result = parameterIsUsable({ name: "demand", index: ["day", "shift"] }, ["day"]);

    expect(result.usable).toBe(false);
    expect(result.reason).toMatch(/shift/);
    expect(result.reason).toMatch(/is not a set/);
  });

  it("uses the plural when more than one is missing", () => {
    const result = parameterIsUsable({ name: "cost", index: ["day", "shift"] }, []);

    expect(result.reason).toMatch(/day and shift/);
    expect(result.reason).toMatch(/are not sets/);
  });
});

describe("variableNameProblem", () => {
  it("accepts a name the contract's pattern allows", () => {
    expect(variableNameProblem("assign_2", [])).toBeNull();
  });

  it("refuses a name the database's CHECK would refuse anyway", () => {
    expect(variableNameProblem("Assign", [])).toMatch(/lower-case/);
    expect(variableNameProblem("2assign", [])).toMatch(/starts with a letter/);
    expect(variableNameProblem("", [])).toMatch(/needs a name/);
  });

  it("refuses a name already in use", () => {
    expect(variableNameProblem("assign", ["assign"])).toMatch(/already something called/);
  });
});

describe("withDomain / cleanVariable", () => {
  it("drops bounds when the variable becomes yes-or-no", () => {
    expect(
      withDomain({ index: ["day"], domain: "integer", lower: 0, upper: 40 }, "binary")
    ).toEqual({ index: ["day"], domain: "binary" });
  });

  it("keeps bounds on an integer or continuous variable", () => {
    expect(
      cleanVariable({ index: ["day"], domain: "continuous", lower: 0.5, upper: 2 })
    ).toEqual({ index: ["day"], domain: "continuous", lower: 0.5, upper: 2 });
  });
});

describe("referencesOf", () => {
  it("finds the sets and names a nested term depends on", () => {
    const term: Term = {
      mul: [
        { const: 8 },
        {
          sum: {
            add: [
              { var: "assign", index: ["e", "d"] },
              { par: "demand", index: ["d"] },
            ],
          },
          over: [{ index: "d", set: "day" }],
        },
      ],
    } as Term;

    const found = referencesOf(term);

    expect([...found.names].sort()).toEqual(["assign", "demand"]);
    expect([...found.sets]).toEqual(["day"]);
  });
});

describe("strandedBy", () => {
  const constraints: Constraint[] = [
    {
      id: "c_cover",
      forall: [{ index: "d", set: "day" }],
      left: { sum: { var: "assign", index: ["e", "d"] }, over: [{ index: "e", set: "employee" }] },
      relation: ">=",
      right: { par: "demand", index: ["d"] },
      severity: "hard",
    } as Constraint,
    {
      id: "c_unrelated",
      forall: [{ index: "s", set: "shift" }],
      left: { const: 0 },
      relation: "<=",
      right: { const: 1 },
      severity: "hard",
    } as Constraint,
  ];
  const objective: ObjectiveTerm[] = [
    { id: "o_shifts", weight: 1, expression: { var: "assign", index: ["e", "d"] } as Term },
  ];

  it("names the rules that would break if a variable went away", () => {
    expect(strandedBy({ kind: "variable", name: "assign" }, constraints, objective)).toEqual([
      "c_cover",
      "o_shifts",
    ]);
  });

  it("names the rules that would break if a parameter went away", () => {
    expect(strandedBy({ kind: "parameter", name: "demand" }, constraints, objective)).toEqual([
      "c_cover",
    ]);
  });

  it("counts a set used only as a binding, not only inside a term", () => {
    // `shift` appears in no term at all -- only as what `c_unrelated` ranges
    // over. Removing it would still break that rule.
    expect(strandedBy({ kind: "set", name: "shift" }, constraints, objective)).toEqual([
      "c_unrelated",
    ]);
  });

  it("reports nothing for a declaration no rule mentions", () => {
    expect(strandedBy({ kind: "variable", name: "unused" }, constraints, objective)).toEqual([]);
  });
});
