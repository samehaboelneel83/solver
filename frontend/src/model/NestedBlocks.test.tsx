import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { checkRule, explain, problemsAt } from "./blockCheck";
import { GoalBlocks, RuleBlocks, RuleSentence } from "./NestedBlocks";
import { ruleSentence, termSentence } from "./ruleSentence";
import type { Constraint, ModelContext, Term } from "./terms";

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
