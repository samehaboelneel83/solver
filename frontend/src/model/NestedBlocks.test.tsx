import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { checkRule, explain, problemsAt } from "./blockCheck";
import { GoalBlocks, RuleBlocks, RuleSentence } from "./NestedBlocks";
import { ruleSentence, termSentence } from "./ruleSentence";
import { rebindSet, type Binding, type Constraint, type ModelContext, type Term } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["person", "day"],
  setIds: {},
  attributes: { person: [{ name: "cap", data_type: "number" }, { name: "team", data_type: "text" }] },
  variables: { hours: { index: ["person"], domain: "continuous" }, open: { index: [], domain: "binary" } },
  parameters: { demand: { index: ["day"] }, budget: { index: [] } },
  relationships: [],
  predictors: { demand_model: { inputs: 2 } },
};

const COVER: Constraint = {
  id: "c_cover",
  forall: [{ index: "d", set: "day" }],
  left: { sum: { var: "hours", index: ["p"] }, over: [{ index: "p", set: "person", where: [{ attr: "team", op: "=", value: "north" }] }] },
  relation: ">=",
  right: { par: "demand", index: ["d"] },
  severity: "hard",
};

describe("the hierarchical check", () => {
  it("finds nothing wrong with a well-formed rule", () => {
    expect(checkRule(COVER, CONTEXT)).toEqual([]);
  });

  it("names each problem at its part, with the path from the rule down to it", () => {
    const broken: Constraint = {
      ...COVER,
      left: { add: [{ var: "hours", index: ["q"] }, { mul: [{ var: "hours", index: ["d"] }, { var: "open", index: [] }] }] },
      right: { par: "demand", index: [] },
    };
    const problems = checkRule(broken, CONTEXT);
    expect(problems.map(explain)).toEqual([
      "left side › term 1: “q” is not bound here: add it to a “for each” or to a total.",
      "right side: Demand takes 1 index (day), not 0.",
    ]);
    // A parent is not itself wrong, but knows how many problems are inside it.
    expect(problemsAt(problems, ["left side"])).toEqual({ own: [], inside: 1 });
    expect(problemsAt(problems, [])).toEqual({ own: [], inside: 2 });
  });

  it("checks what only the whole can see: a total's letters, a product's degree, a rule with no decision", () => {
    const reused: Constraint = { ...COVER, left: { sum: { var: "hours", index: ["d"] }, over: [{ index: "d", set: "person" }] } };
    expect(checkRule(reused, CONTEXT).map((p) => p.message)).toContain("“d” already names something here; pick another letter");
    const cubic: Term = { mul: [{ var: "open", index: [] }, { mul: [{ var: "open", index: [] }, { var: "open", index: [] }] }] };
    expect(checkRule({ ...COVER, forall: [], left: cubic, right: { const: 1 } }, CONTEXT).map((p) => p.level)).toContain("operation");
    expect(checkRule({ ...COVER, left: { par: "demand", index: ["d"] }, right: { const: 3 } }, CONTEXT).map(explain))
      .toEqual(["comparison: Neither side reads a decision, so nothing the solver chooses can keep or break this rule."]);
  });

  it("checks a prediction against the trained models the problem declares", () => {
    const rule: Constraint = { ...COVER, forall: [], left: { predict: "demand_model", of: [{ var: "open", index: [] }] }, right: { const: 1 } };
    expect(checkRule(rule, CONTEXT).map((p) => p.message)).toEqual(["demand_model reads 2 inputs, not 1"]);
  });
});

describe("the plain-language reading", () => {
  it("reads a rule the way a person would say it", () => {
    expect(ruleSentence(COVER)).toBe(
      "For every day d, the total of hours of p, over every person p whose team is north, must be at least demand of d.",
    );
    expect(ruleSentence({ ...COVER, forall: [], left: { var: "open", index: [] }, relation: "<=", right: { const: 1 }, severity: "soft", weight: 3 }))
      .toBe("Open must be at most 1. It is preferred, not required (weight 3).");
    expect(termSentence({ add: [{ par: "budget", index: [] }, { mul: [{ const: -1 }, { var: "open", index: [] }] }] })).toBe("budget minus open");
    expect(termSentence({ fn: "log", of: { var: "open", index: [] } })).toBe("the natural logarithm of open");
  });
});

function Harness({ initial }: { initial: Constraint }) {
  const [rule, setRule] = useState(initial);
  return (
    <>
      <RuleBlocks rule={rule} context={CONTEXT} onChange={setRule} />
      <pre data-testid="ir">{JSON.stringify(rule)}</pre>
    </>
  );
}

const ir = () => JSON.parse(screen.getByTestId("ir").textContent ?? "{}") as Constraint;

describe("the boxes", () => {
  it("nests each part inside its parent, coloured by what it is", () => {
    render(<Harness initial={COVER} />);
    const blocks = screen.getAllByTestId("block").map((box) => box.getAttribute("data-role"));
    expect(blocks).toEqual(["rule", "scope", "comparison", "total", "decision", "data"]);
    const total = screen.getByRole("group", { name: "Total: left side" });
    expect(within(total).getByRole("group", { name: "Decision: what is totalled" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Complete");
  });

  it("offers only the names bound around a box, and only numbers where a number goes", () => {
    render(<Harness initial={COVER} />);
    const which = screen.getByLabelText("hours: which person") as HTMLSelectElement;
    expect(Array.from(which.options).map((o) => o.value)).toEqual(["d", "p"]);
    const menu = screen.getByLabelText("Change right side") as HTMLSelectElement;
    const offered = Array.from(menu.querySelectorAll("optgroup[label='Replace it with'] option")).map((o) => o.textContent);
    expect(offered).toEqual(["a number", "a decision", "data", "a total over a set", "adding things up", "multiplying two things",
      "a function (log, square root…)", "a trained model's prediction"]);
  });

  it("edits the tree, and a problem made deep inside shows at its box and above it", () => {
    render(<Harness initial={COVER} />);
    fireEvent.change(screen.getByLabelText("Comparison"), { target: { value: "<=" } });
    expect(ir().relation).toBe("<=");
    fireEvent.change(screen.getByLabelText("Change right side"), { target: { value: "wrap:mul" } });
    expect(ir().right).toEqual({ mul: [{ const: 1 }, { par: "demand", index: ["d"] }] });
    fireEvent.change(screen.getByLabelText("factor 1: number"), { target: { value: "2" } });
    expect(ir().right).toEqual({ mul: [{ const: 2 }, { par: "demand", index: ["d"] }] });

    // Rename the total's letter: the decision inside no longer reads a bound name.
    fireEvent.change(screen.getByLabelText("left side: runs over: name 1"), { target: { value: "x" } });
    expect(screen.getByRole("status")).toHaveTextContent("1 thing to fix");
    expect(screen.getByRole("status")).toHaveTextContent("left side › what is totalled: “p” is not bound here");
    expect(within(screen.getByRole("group", { name: "Total: left side" })).getByText("1 problem inside")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Decision: what is totalled" })).getByText(/“p” is not bound here/)).toBeInTheDocument();
  });

  it("adds and removes the terms of a sum", () => {
    render(<Harness initial={{ ...COVER, right: { add: [{ par: "demand", index: ["d"] }, { const: 1 }] } }} />);
    fireEvent.click(screen.getByRole("button", { name: "+ add a term" }));
    expect((ir().right as { add: Term[] }).add).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Change term 2"), { target: { value: "remove" } });
    expect(ir().right).toEqual({ add: [{ par: "demand", index: ["d"] }, { const: 0 }] });
  });

  it("shows a goal as boxes and says when it reads no decision", () => {
    render(<GoalBlocks label="o_cost" expression={{ par: "budget", index: [] }} context={CONTEXT} onChange={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("The goal reads no decision");
  });
});

describe("the sentence, with blanks to fill in", () => {
  function Sentence({ initial }: { initial: Constraint }) {
    const [rule, setRule] = useState(initial);
    return (
      <>
        <RuleSentence rule={rule} context={CONTEXT} onEdit={() => {}} onChange={setRule} />
        <pre data-testid="ir">{JSON.stringify(rule)}</pre>
      </>
    );
  }

  it("changes a leaf of the rule from its words, and reads back the change", () => {
    render(<Sentence initial={{ ...COVER, right: { add: [{ par: "demand", index: ["d"] }, { mul: [{ const: -1 }, { const: 2 }] }] } }} />);
    expect(screen.getByTestId("sentence-reading")).toHaveTextContent(
      "For every day d, the total of hours of p, over every person p whose team is north, must be at least demand of d minus 2.",
    );
    fireEvent.change(screen.getByLabelText("right side › term 2: number"), { target: { value: "3" } });
    expect(ir().right).toEqual({ add: [{ par: "demand", index: ["d"] }, { mul: [{ const: -1 }, { const: 3 }] }] });
    fireEvent.change(screen.getByLabelText("comparison"), { target: { value: "<=" } });
    fireEvent.change(screen.getByLabelText("left side › what is totalled: decision"), { target: { value: "open" } });
    expect(ir().left).toEqual({ sum: { var: "open", index: [] }, over: [{ index: "p", set: "person", where: [{ attr: "team", op: "=", value: "north" }] }] });
    fireEvent.change(screen.getByLabelText("for each: set 1"), { target: { value: "person" } });
    expect(ir().forall).toEqual([{ index: "d", set: "person" }]);
    expect(screen.getByTestId("sentence-reading")).toHaveTextContent("must be at most");
  });
});

describe("only some of them: a binding's conditions", () => {
  function Sentence({ initial }: { initial: Constraint }) {
    const [rule, setRule] = useState(initial);
    return (
      <>
        <RuleSentence rule={rule} context={CONTEXT} onEdit={() => {}} onChange={setRule} />
        <pre data-testid="ir">{JSON.stringify(rule)}</pre>
      </>
    );
  }

  it("edits a condition in the sentence: attribute, comparison in words, and a value that fits", () => {
    render(<Sentence initial={COVER} />);
    const name = "left side: runs over: set 1: condition 1";
    const comparison = screen.getByLabelText(`${name}: comparison`) as HTMLSelectElement;
    // Text is compared for equality or membership, not ordered.
    expect(Array.from(comparison.options).map((o) => o.textContent)).toEqual(["is", "is not", "is one of", "is not one of"]);
    fireEvent.change(comparison, { target: { value: "in" } });
    fireEvent.change(screen.getByLabelText(`${name}: value`), { target: { value: "north, south" } });
    expect(ir().left).toMatchObject({ over: [{ where: [{ attr: "team", op: "in", value: ["north", "south"] }] }] });
    expect(screen.getByTestId("sentence-reading")).toHaveTextContent("whose team is one of north, south");

    // A number attribute offers every comparison, and reads its value as a number.
    fireEvent.change(screen.getByLabelText(`${name}: attribute`), { target: { value: "cap" } });
    expect(Array.from((screen.getByLabelText(`${name}: comparison`) as HTMLSelectElement).options).map((o) => o.value))
      .toEqual(["=", "!=", "<", "<=", ">", ">=", "in", "notIn"]);
    fireEvent.change(screen.getByLabelText(`${name}: comparison`), { target: { value: ">=" } });
    fireEvent.change(screen.getByLabelText(`${name}: value`), { target: { value: "2" } });
    expect(ir().left).toMatchObject({ over: [{ where: [{ attr: "cap", op: ">=", value: 2 }] }] });

    // Removing the last condition takes `where` off the binding.
    fireEvent.click(screen.getByRole("button", { name: `Remove ${name}` }));
    expect((ir().left as { over: object[] }).over[0]).toEqual({ index: "p", set: "person" });
  });

  it("adds a condition in the boxes, and the check names one that no longer fits", () => {
    render(<Harness initial={{ ...COVER, left: { sum: { var: "hours", index: ["p"] }, over: [{ index: "p", set: "person" }] } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Only some of person: add a condition to left side: runs over: set 1" }));
    expect(ir().left).toMatchObject({ over: [{ where: [{ attr: "cap", op: "=", value: 0 }] }] });
    expect(screen.getByRole("status")).toHaveTextContent("Complete");
    fireEvent.change(screen.getByLabelText("left side: runs over: set 1: condition 1: value"), { target: { value: "lots" } });
    expect(screen.getByRole("status")).toHaveTextContent("left side: Cap is a number, so compare it with a number");
    // A day has no attributes: changing the set drops conditions that were about a person.
    fireEvent.change(screen.getByLabelText("left side: runs over: set 1"), { target: { value: "day" } });
    expect((ir().left as { over: object[] }).over[0]).toEqual({ index: "p", set: "day" });
  });

  it("checks conditions against the set's attributes", () => {
    const rule: Constraint = { ...COVER, forall: [{ index: "d", set: "person", where: [{ attr: "age", op: "=", value: 1 }, { attr: "team", op: "<", value: "a" }] }] };
    expect(checkRule(rule, CONTEXT).map(explain)).toEqual([
      "for each: Person has nothing called “age” to compare.",
      "for each: Team cannot be compared with “is below”.",
    ]);
  });
});


describe("walks along a relationship (a hierarchy)", () => {
  const ORG: ModelContext = {
    sets: ["employee", "unit"],
    setIds: {},
    attributes: { employee: [{ name: "grade", data_type: "number" }], unit: [] },
    variables: { assign: { index: ["employee"], domain: "binary" } },
    parameters: {},
    predictors: {},
    relationships: [
      { name: "manages", from: "employee", to: "employee", hierarchy: true, attributes: [{ name: "weight", data_type: "number" }] },
      { name: "belongs", from: "employee", to: "unit" },
    ],
  };
  // TRAVERSE: start m, relation manages, going down, 1 or more steps, grade >= 2, body: weight along the path × assign.
  const TEAM: Constraint = {
    id: "c_team",
    forall: [{ index: "m", set: "employee" }],
    left: {
      sum: { mul: [{ attr: { of: "r", name: "weight", along: "sum" } }, { var: "assign", index: ["e"] }] },
      over: [{ index: "e", set: "employee", where: [{ attr: "grade", op: ">=", value: 2 }], via: { rel: "manages", from: "m", depth: "any", as: "r" } }],
    },
    relation: "<=",
    right: { const: 5 },
    severity: "hard",
  };

  function Walks({ initial, boxes = false }: { initial: Constraint; boxes?: boolean }) {
    const [rule, setRule] = useState(initial);
    return (
      <>
        {boxes
          ? <RuleBlocks rule={rule} context={ORG} onChange={setRule} />
          : <RuleSentence rule={rule} context={ORG} onEdit={() => {}} onChange={setRule} />}
        <pre data-testid="ir">{JSON.stringify(rule)}</pre>
      </>
    );
  }
  const over = () => (ir().left as { over: Binding[] }).over[0];

  it("reads start, relationship, direction, depth, condition and the links' numbers, and checks out", () => {
    expect(checkRule(TEAM, ORG)).toEqual([]);
    expect(ruleSentence(TEAM, ORG.relationships)).toBe(
      "For every employee m, the total of the sum of weight along r times assign of e, over every employee e whose grade is at least 2, " +
        "below m by manages in 1 or more steps (each link called r), must be at most 5.",
    );
    // Not a hierarchy: no "below", and a link from a set to itself goes forwards or backwards.
    const flat = ORG.relationships.map((r) => ({ ...r, hierarchy: false }));
    expect(ruleSentence(TEAM, flat)).toContain("linked from m by manages in 1 or more steps");
    render(<RuleSentence rule={TEAM} context={{ ...ORG, relationships: flat }} onEdit={() => {}} onChange={() => {}} />);
    expect(Array.from((screen.getByLabelText("left side: runs over: set 1: walk: relationship") as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(["manages, forwards", "manages, backwards", "manages, either way"]);
  });

  it("says why no link is offered, where the model has one that could reach the set", () => {
    render(<Walks initial={{ ...TEAM, forall: [], left: { sum: { var: "assign", index: ["e"] }, over: [{ index: "e", set: "employee" }] } }} />);
    expect(screen.queryByRole("button", { name: /Reach employee through a relationship/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Why no link: left side: runs over: set 1" }));
    expect(screen.getByRole("note")).toHaveTextContent("A link starts at an item picked before this one. To reach employee through manages (from its employee end)");
  });

  it("keeps what still fits when a set changes, and can undo what did not", () => {
    render(<Walks initial={TEAM} boxes />);
    fireEvent.change(screen.getByLabelText("left side: runs over: set 1"), { target: { value: "unit" } });
    expect(over()).toEqual({ index: "e", set: "unit" });
    expect(screen.getByText(/its conditions and the link by manages did not fit the new set/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo the change of set: left side: runs over: set 1" }));
    expect(over()).toEqual(TEAM.left && (TEAM.left as { over: Binding[] }).over[0]);
  });

  it("keeps a condition the new set can also take, and a walk that still reaches it", () => {
    const both: ModelContext = { ...ORG, attributes: { ...ORG.attributes, unit: [{ name: "grade", data_type: "number" }] } };
    const moved = rebindSet({ index: "e", set: "employee", where: [{ attr: "grade", op: ">=", value: 2 }], via: { rel: "belongs", from: "m" } }, "unit", both, [{ index: "m", set: "employee" }]);
    expect(moved).toEqual({ index: "e", set: "unit", where: [{ attr: "grade", op: ">=", value: 2 }], via: { rel: "belongs", from: "m" } });
  });

  it("names a link's number as data of a link", () => {
    render(<Walks initial={TEAM} boxes />);
    expect(screen.getByRole("group", { name: "Data along the links: factor 1" })).toBeInTheDocument();
  });

  it("edits the walk in the sentence: how far, which way, and removing it", () => {
    render(<Walks initial={TEAM} />);
    const walk = "left side: runs over: set 1: walk";
    expect(Array.from((screen.getByLabelText(`${walk}: relationship`) as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(["manages, going down", "manages, going up", "manages, either way"]);
    expect(screen.getByTestId("sentence-reading")).toHaveTextContent("below m by manages");
    fireEvent.change(screen.getByLabelText(`${walk}: how far`), { target: { value: "any_or_self" } });
    expect(over().via).toEqual({ rel: "manages", from: "m", depth: "any_or_self", as: "r" });
    fireEvent.change(screen.getByLabelText(`${walk}: relationship`), { target: { value: "manages:to" } });
    expect(over().via).toEqual({ rel: "manages", to: "m", depth: "any_or_self", as: "r" });
    fireEvent.change(screen.getByLabelText(`${walk}: how far`), { target: { value: "one" } });
    expect(over().via).toEqual({ rel: "manages", to: "m", as: "r" });
    // One link has one weight: the check asks to drop "the sum of".
    expect(screen.getByRole("status")).toHaveTextContent("“r” is one link, so its weight has one value");
    fireEvent.click(screen.getByRole("button", { name: `Remove ${walk}` }));
    expect(over().via).toBeUndefined();
    // And a walk can be added back where one is possible.
    fireEvent.click(screen.getByRole("button", { name: "Reach employee through a relationship: left side: runs over: set 1" }));
    expect(over().via).toEqual({ rel: "manages", from: "m" });
  });

  it("offers the links as something to read a number from, and says how the links of a path combine", () => {
    render(<Walks initial={TEAM} boxes />);
    const which = screen.getByLabelText("factor 1: of which item") as HTMLSelectElement;
    expect(Array.from(which.options).map((o) => o.textContent)).toEqual(["m (employee)", "e (employee)", "r (links by manages)"]);
    fireEvent.change(screen.getByLabelText("factor 1: how the links combine"), { target: { value: "max" } });
    expect((ir().left as { sum: { mul: Term[] } }).sum.mul[0]).toEqual({ attr: { of: "r", name: "weight", along: "max" } });
    fireEvent.change(which, { target: { value: "e" } });
    expect((ir().left as { sum: { mul: Term[] } }).sum.mul[0]).toEqual({ attr: { of: "e", name: "grade" } });
  });

  it("takes the combination off when the walk is cut back to one step", () => {
    render(<Walks initial={TEAM} boxes />);
    fireEvent.change(screen.getByLabelText("left side: runs over: set 1: walk: how far"), { target: { value: "one" } });
    expect(screen.getByRole("status")).toHaveTextContent("“r” is one link, so its weight has one value");
    fireEvent.change(screen.getByLabelText("factor 1: how the links combine"), { target: { value: "" } });
    expect((ir().left as { sum: { mul: Term[] } }).sum.mul[0]).toEqual({ attr: { of: "r", name: "weight" } });
    expect(screen.getByRole("status")).toHaveTextContent("Complete");
  });

  it("changing the set drops the walk and conditions that were about the old one", () => {
    render(<Walks initial={TEAM} boxes />);
    fireEvent.change(screen.getByLabelText("left side: runs over: set 1"), { target: { value: "unit" } });
    expect(over()).toEqual({ index: "e", set: "unit" });
  });

  it("names a walk that cannot be taken", () => {
    const bad = (via: Binding["via"], set = "employee"): string[] =>
      checkRule({ ...TEAM, left: { sum: { var: "assign", index: ["e"] }, over: [{ index: "e", set, via }] } }, ORG).map((p) => p.message);
    expect(bad({ rel: "reports", from: "m" })).toEqual(["“reports” is not a relationship of this model"]);
    expect(bad({ rel: "manages", from: "x" })).toEqual(["the walk starts at “x”, which is not bound before it"]);
    expect(bad({ rel: "belongs", from: "m" })).toEqual(["walking belongs from employee reaches unit, not employee"]);
    expect(bad({ rel: "belongs", from: "m", depth: "any" }, "unit").at(-1))
      .toBe("only a relationship from a set to itself can be walked more than one step; belongs links employee to unit");
    expect(bad({ rel: "manages", from: "m", as: "m" })).toEqual(["“m” already names something here; pick another name for the links"]);
  });
});

describe("condition values that are picked, not typed", () => {
  const SHOP: ModelContext = {
    ...CONTEXT,
    attributes: { person: [
      { name: "team", data_type: "enum", enum_values: ["north", "south", "east"] },
      { name: "joined", data_type: "date" },
    ] },
  };
  function Picked({ initial }: { initial: Constraint }) {
    const [rule, setRule] = useState(initial);
    return (
      <>
        <RuleBlocks rule={rule} context={SHOP} onChange={setRule} />
        <pre data-testid="ir">{JSON.stringify(rule)}</pre>
      </>
    );
  }
  const where = () => (ir().left as { over: Binding[] }).over[0].where;
  const name = "left side: runs over: set 1: condition 1";

  it("offers a list's choices, one or several, and a date as a date", () => {
    render(<Picked initial={COVER} />);
    const value = screen.getByLabelText(`${name}: value`) as HTMLSelectElement;
    expect(Array.from(value.options).map((o) => o.value)).toEqual(["north", "south", "east"]);
    fireEvent.change(value, { target: { value: "east" } });
    expect(where()).toEqual([{ attr: "team", op: "=", value: "east" }]);
    fireEvent.change(screen.getByLabelText(`${name}: comparison`), { target: { value: "in" } });
    const several = screen.getByRole("group", { name: `${name}: value` });
    fireEvent.click(within(several).getByLabelText("north"));
    expect(where()).toEqual([{ attr: "team", op: "in", value: ["north", "east"] }]);
    fireEvent.change(screen.getByLabelText(`${name}: attribute`), { target: { value: "joined" } });
    fireEvent.change(screen.getByLabelText(`${name}: comparison`), { target: { value: ">=" } });
    const date = screen.getByLabelText(`${name}: value`) as HTMLInputElement;
    expect(date.type).toBe("date");
    fireEvent.change(date, { target: { value: "2026-01-31" } });
    expect(where()).toEqual([{ attr: "joined", op: ">=", value: "2026-01-31" }]);
  });

  it("names a value that is not one of the choices", () => {
    const rule: Constraint = { ...COVER, forall: [{ index: "q", set: "person", where: [{ attr: "team", op: "in", value: ["north", "west"] }] }] };
    expect(checkRule(rule, SHOP).map((p) => p.message)).toContain("“west” is not one of team’s choices (north, south, east)");
  });
});

describe("walks narrowed further, and conditions joined with or", () => {
  const ORG: ModelContext = {
    sets: ["employee", "unit"],
    setIds: {},
    attributes: { employee: [{ name: "grade", data_type: "number" }, { name: "band", data_type: "text" }], unit: [] },
    variables: { pick: { index: ["employee"], domain: "binary" } },
    parameters: {},
    predictors: {},
    relationships: [
      { name: "manages", from: "employee", to: "employee", hierarchy: true, attributes: [{ name: "weight", data_type: "number" }] },
      { name: "belongs", from: "employee", to: "unit" },
    ],
  };
  const START: Constraint = {
    id: "c",
    forall: [{ index: "m", set: "employee" }],
    left: { sum: { var: "pick", index: ["e"] }, over: [{ index: "e", set: "employee", via: { rel: "manages", from: "m" } }] },
    relation: "<=",
    right: { const: 1 },
    severity: "hard",
  };
  function Edit({ boxes = false }: { boxes?: boolean }) {
    const [rule, setRule] = useState(START);
    return (
      <>
        {boxes
          ? <RuleBlocks rule={rule} context={ORG} onChange={setRule} />
          : <RuleSentence rule={rule} context={ORG} onEdit={() => {}} onChange={setRule} />}
        <pre data-testid="ir">{JSON.stringify(rule)}</pre>
      </>
    );
  }
  const walk = "left side: runs over: set 1: walk";
  const over = () => (ir().left as { over: Binding[] }).over[0];

  it("walks a number of steps, either way, through some links only, on a day", () => {
    render(<Edit />);
    fireEvent.change(screen.getByLabelText(`${walk}: how far`), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText(`${walk}: fewest steps`), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(`${walk}: most steps`), { target: { value: "3" } });
    expect(over().via).toEqual({ rel: "manages", from: "m", steps: { min: 2, max: 3 } });
    fireEvent.change(screen.getByLabelText(`${walk}: most steps`), { target: { value: "" } });
    expect(over().via?.steps).toEqual({ min: 2 });

    fireEvent.change(screen.getByLabelText(`${walk}: relationship`), { target: { value: "manages:both" } });
    expect(over().via).toEqual({ rel: "manages", both: "m", steps: { min: 2 } });

    fireEvent.click(screen.getByRole("button", { name: `Only some of manages links: add a condition to ${walk} links` }));
    fireEvent.change(screen.getByLabelText(`${walk} links: condition 1: comparison`), { target: { value: ">" } });
    expect(over().via?.where).toEqual([{ attr: "weight", op: ">", value: 0 }]);

    fireEvent.click(screen.getByRole("button", { name: `Only the links valid on a day: ${walk}` }));
    fireEvent.change(screen.getByLabelText(`${walk}: on the day`), { target: { value: "2026-10-01" } });
    expect(over().via?.on).toBe("2026-10-01");
    expect(screen.getByTestId("sentence-reading")).toHaveTextContent(
      "over every employee e linked either way to m by manages in 2 or more steps through links whose weight is above 0 on 2026-10-01",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Complete");
    fireEvent.click(screen.getByRole("button", { name: `Any day: ${walk}` }));
    expect(over().via?.on).toBeUndefined();
  });

  it("turns a condition into “this or that”, and back when one is left", () => {
    render(<Edit boxes />);
    const set = "left side: runs over: set 1";
    fireEvent.click(screen.getByRole("button", { name: `Only some of employee: add a condition to ${set}` }));
    fireEvent.click(screen.getByRole("button", { name: `Or: another way for ${set}: condition 1` }));
    fireEvent.change(screen.getByLabelText(`${set}: condition 1 or 2: attribute`), { target: { value: "band" } });
    fireEvent.change(screen.getByLabelText(`${set}: condition 1 or 2: value`), { target: { value: "senior" } });
    expect(over().where).toEqual([{ any: [{ attr: "grade", op: "=", value: 0 }, { attr: "band", op: "=", value: "senior" }] }]);
    expect(screen.getByRole("group", { name: `${set}: condition 1: any of` })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `Remove ${set}: condition 1 or 1` }));
    expect(over().where).toEqual([{ attr: "band", op: "=", value: "senior" }]);
  });

  it("names what cannot be walked: either way between two sets, a bad range, a link condition on nothing", () => {
    const bad = (via: Binding["via"], set = "employee") =>
      checkRule({ ...START, left: { sum: { var: "pick", index: ["e"] }, over: [{ index: "e", set, via }] } }, ORG).map((p) => p.message);
    expect(bad({ rel: "belongs", both: "m" }, "unit")[0]).toMatch(/cannot be walked either way/);
    expect(bad({ rel: "manages", from: "m", steps: { min: 3, max: 2 } })).toEqual(["steps go from a whole number to a whole number no smaller, and at least 1"]);
    expect(bad({ rel: "manages", from: "m", where: [{ attr: "colour", op: "=", value: 1 }] })).toEqual(["a manages link has nothing called “colour” to compare"]);
    expect(bad({ rel: "manages", from: "m", on: "soon" })).toEqual(["“soon” is not a day; write it YYYY-MM-DD"]);
  });
});
