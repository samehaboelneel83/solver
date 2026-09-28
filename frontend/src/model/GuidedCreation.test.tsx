import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import GuidedCreation from "./GuidedCreation";
import { applyGuidedCommand } from "./guidedCommands";
import { formDraftOf } from "./draftIr";

function Harness({ withParameters = false }: { withParameters?: boolean }) {
  const [draft, setDraft] = useState(() => formDraftOf(withParameters
    ? { sets: ["employee", "day"], variables: { assign: { domain: "binary", index: ["employee", "day"] } }, parameters: { cost: { index: ["employee"] }, demand: { index: ["day"] } }, constraints: [] }
    : { sets: [], variables: {}, constraints: [] }));
  return <><GuidedCreation draft={draft} availableSets={["employee", "day"]} onApply={command => setDraft(current => applyGuidedCommand(current, command, ["employee", "day"]))} />
    <div data-testid="draft">{JSON.stringify(draft)}</div></>;
}
const draft = () => JSON.parse(screen.getByTestId("draft").textContent!);

it("builds a parameter-backed limit and cost objective without typing expressions", () => {
  render(<Harness withParameters />);
  fireEvent.click(screen.getByRole("button", { name: "2. Rule" }));
  fireEvent.change(screen.getByLabelText("Rule name"), { target: { value: "coverage" } });
  fireEvent.change(screen.getByLabelText("Decision to use"), { target: { value: "assign" } });
  fireEvent.click(screen.getByLabelText("day (dimension 2)"));
  fireEvent.change(screen.getByLabelText("Limit source"), { target: { value: "parameter" } });
  fireEvent.change(screen.getByLabelText("Limit parameter: parameter"), { target: { value: "demand" } });
  fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
  expect(draft().constraints[0].right).toEqual({ par: "demand", index: ["i2"] });
  fireEvent.click(screen.getByRole("button", { name: "3. Objective" }));
  fireEvent.change(screen.getByLabelText("Objective term name"), { target: { value: "total_cost" } });
  fireEvent.change(screen.getByLabelText("Multiply each decision by: parameter"), { target: { value: "cost" } });
  fireEvent.click(screen.getByRole("button", { name: "Add objective term" }));
  expect(draft().objective.terms[0].expression.sum.mul[0]).toEqual({ par: "cost", index: ["i1"] });
});

it("lets an end user create a variable, a per-day rule and an objective using only forms", () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("Decision name"), { target: { value: "assign" } });
  fireEvent.click(screen.getByLabelText("employee", { exact: true }));
  fireEvent.click(screen.getByLabelText("day", { exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "Create decision variable" }));
  expect(screen.getByRole("status")).toHaveTextContent("assign added");
  expect(draft().variables.assign).toEqual({ domain: "binary", index: ["employee", "day"] });

  fireEvent.click(screen.getByRole("button", { name: "2. Rule" }));
  fireEvent.change(screen.getByLabelText("Rule name"), { target: { value: "daily_capacity" } });
  fireEvent.change(screen.getByLabelText("Decision to use"), { target: { value: "assign" } });
  fireEvent.click(screen.getByLabelText("day (dimension 2)"));
  fireEvent.change(screen.getByLabelText("Limit", { exact: true }), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
  expect(draft().constraints[0].forall).toEqual([{ index: "i2", set: "day" }]);
  expect(draft().constraints[0].left.over).toEqual([{ index: "i1", set: "employee" }]);

  fireEvent.click(screen.getByRole("button", { name: "3. Objective" }));
  fireEvent.change(screen.getByLabelText("Objective term name"), { target: { value: "total_assignments" } });
  fireEvent.change(screen.getByLabelText("Optimization direction"), { target: { value: "maximize" } });
  fireEvent.click(screen.getByRole("button", { name: "Add objective term" }));
  expect(draft().objective.sense).toBe("maximize");
  expect(draft().objective.terms[0].expression.sum.var).toBe("assign");
  expect(draft().constraints).toHaveLength(1);
});

it("explains invalid bounds and prevents creating an invalid decision", () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText("Decision name"), { target: { value: "staff" } });
  fireEvent.change(screen.getByLabelText("What kind of decision?"), { target: { value: "integer" } });
  fireEvent.change(screen.getByLabelText("Minimum (optional)"), { target: { value: "2.5" } });
  expect(screen.getByRole("button", { name: "Create decision variable" })).toBeDisabled();
  expect(screen.getByText("Whole-number decisions need whole-number bounds.")).toBeInTheDocument();
  expect(Object.keys(draft().variables)).toHaveLength(0);
});

it("does not enable a rule or objective before a decision exists", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "2. Rule" }));
  expect(screen.getByRole("button", { name: "Create rule" })).toBeDisabled();
  expect(within(screen.getByRole("region", { name: "Create with guided forms" })).getByText(/Create a decision variable first/)).toBeInTheDocument();
});
