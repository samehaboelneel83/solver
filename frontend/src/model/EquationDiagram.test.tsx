import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { GoalDiagram, RuleDiagram } from "./EquationDiagram";
import type { Constraint, ModelContext, Term } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["person"], setIds: {}, relationships: [],
  attributes: { person: [{ name: "capacity", data_type: "number" }, { name: "team", data_type: "text" }] },
  variables: { hours: { index: ["person"], domain: "continuous" } },
  parameters: {},
};

const RULE: Constraint = {
  id: "c_capacity", severity: "hard",
  forall: [{ index: "p", set: "person" }],
  left: { var: "hours", index: ["p"] },
  relation: "<=",
  right: { attr: { of: "p", name: "capacity" } },
};

// sum(((hours[p] + 1) * hours[p]) for p in person where team = "north")
const DEEP: Term = {
  sum: { mul: [{ add: [{ var: "hours", index: ["p"] }, { const: 1 }] }, { var: "hours", index: ["p"] }] },
  over: [{ index: "p", set: "person", where: [{ attr: "team", op: "=", value: "north" }] }],
};

it("shows a rule's parts side by side: what it ranges over, its sides and the relation", () => {
  render(<RuleDiagram rule={RULE} context={CONTEXT} onChange={vi.fn()} />);
  const diagram = screen.getByTestId("rule-diagram");
  expect(within(diagram).getByText("for each")).toBeInTheDocument();
  expect(within(diagram).getByText("left side")).toBeInTheDocument();
  expect(within(diagram).getByText("<=")).toBeInTheDocument();
  expect(within(diagram).getByText("right side")).toBeInTheDocument();
  expect(within(diagram).getByText("capacity[p]")).toBeInTheDocument();
});

it("walks down a goal recursively, one box at a time, to its leaves", () => {
  render(<GoalDiagram label="o_even" expression={DEEP} context={CONTEXT} onChange={vi.fn()} />);
  // The goal is open: its sum shows "over" and "of", both closed.
  expect(screen.getByRole("button", { name: "Close o_even" })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Open over" }));
  expect(screen.getByRole("listitem")).toHaveTextContent('p in personwhere team = "north"');
  fireEvent.click(screen.getByRole("button", { name: "Open of" }));
  // A product: two factors joined by ×.
  expect(screen.getByText("×")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open factor 1" }));
  // Added together: two terms joined by +.
  expect(screen.getByText("+")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open term 1" }));
  // Down to the variable's index, with its set.
  expect(screen.getByText("(person)")).toBeInTheDocument();
  // A number is a leaf: nothing to open.
  expect(screen.queryByRole("button", { name: "Open term 2" })).toBeNull();
});

it("opens and closes every level at once", () => {
  render(<GoalDiagram label="o_even" expression={DEEP} context={CONTEXT} onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Open all" }));
  expect(screen.getAllByText("(person)").length).toBeGreaterThanOrEqual(2);
  fireEvent.click(screen.getByRole("button", { name: "Close all" }));
  expect(screen.queryByText("×")).toBeNull();
});

it("edits one part in place, with the rule's indices in scope, and nothing else", () => {
  const onChange = vi.fn();
  render(<RuleDiagram rule={RULE} context={CONTEXT} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit right side" }));
  const field = screen.getByLabelText("Equation for right side");
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: "2 * capacity[p]" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(onChange).toHaveBeenCalledWith({ ...RULE, right: { mul: [{ const: 2 }, { attr: { of: "p", name: "capacity" } }] } });
});
