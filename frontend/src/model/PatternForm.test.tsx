import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { FormDraft } from "./draftIr";
import PatternForm, { unitMismatch } from "./PatternForm";
import { MappingPreview } from "./GuidedCreation";
import ModelReview, { reviewNotes } from "./ModelReview";

const draft = (): FormDraft => ({
  sets: [], parameters: { length: { index: ["job"] }, need: { index: ["job"] }, cap: { index: [] } }, variables: {}, constraints: [],
  objective: { sense: "minimize", mode: "weighted", terms: [] },
});

it("adds a task pattern whole, saying in words what it adds", () => {
  const onApply = vi.fn();
  render(<PatternForm draft={draft()} availableSets={["job"]} relationships={[]} units={{ length: "hours" }} onApply={onApply} />);
  fireEvent.change(screen.getByLabelText("Task name"), { target: { value: "op" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "job" }));
  fireEvent.change(screen.getByLabelText("Duration: from"), { target: { value: "parameter" } });
  expect(screen.getByLabelText("Duration: parameter")).toHaveTextContent("length (hours)");
  expect(screen.getByLabelText("Pattern summary")).toHaveTextContent("Adds the decision op_start (whole number); the decision op_end (whole number); the task op for each job, lasting length.");
  fireEvent.click(screen.getByRole("button", { name: "Add task with a duration" }));
  expect(onApply).toHaveBeenCalledWith({ kind: "task", name: "op", index: ["job"], size: { parameter: "length" }, horizon: 100, optional: false });
});

it("explains why a scheduling pattern cannot be added yet", () => {
  render(<PatternForm draft={draft()} availableSets={["job"]} relationships={[]} units={{}} onApply={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "One at a time" }));
  expect(screen.getByText("Add a task first, with the Task with a duration pattern.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add one at a time" })).toBeDisabled();
});

it("warns when two compared parameters carry different units", () => {
  expect(unitMismatch({ need: "kg", cap: "tonnes" }, "need", "cap")).toBe("need is in kg and cap in tonnes: the rule compares them as they are, so check they measure the same thing.");
  expect(unitMismatch({ need: "kg", cap: "kg" }, "need", "cap")).toBeNull();
  expect(unitMismatch({ need: "kg" }, "need", "cap")).toBeNull();
});

it("says a parameter's mapping plainly, and why a dimension is not mapped", () => {
  render(<MappingPreview name="demand" parameterIndex={["shift"]} dimensions={[-1]} decision="staff" decisionIndex={["nurse", "shift"]} allowed={[]} unit="people" />);
  expect(screen.getByLabelText("Mapping of demand")).toHaveTextContent("demand[shift ← ?] in people");
  expect(screen.getByText(/staff's shift is added together here; a limit can only follow a dimension kept separate/)).toBeInTheDocument();
});

it("reviews the whole model in words and flags what looks unfinished", () => {
  const d: FormDraft = {
    sets: ["shift"], parameters: { demand: { index: ["shift"] }, unused: { index: [] } },
    variables: { staff: { domain: "integer", index: ["shift"], lower: 0 }, idle: { domain: "binary", index: [] } },
    constraints: [{ id: "cover", forall: [{ index: "s", set: "shift" }], severity: "soft", weight: 5, relation: ">=",
      left: { var: "staff", index: ["s"] }, right: { par: "demand", index: ["s"] }, note: "enough people each shift" }],
    objective: { sense: "minimize", mode: "weighted", terms: [{ id: "wages", weight: 1, expression: { sum: { var: "staff", index: ["s"] }, over: [{ index: "s", set: "shift" }] } }] },
  };
  render(<ModelReview draft={d} units={{ demand: "people" }} planner={["A mixed solver will take this."]} />);
  const review = screen.getByRole("region", { name: "Model review" });
  expect(review).toHaveTextContent("staff: a whole number, for each shift, from 0 to no stated limit.");
  expect(review).toHaveTextContent("demand: for each shift, in people.");
  expect(review).toHaveTextContent("cover (may bend, at 5 per unit)");
  expect(review).toHaveTextContent("for each s in shift: staff[s] >= demand[s]");
  expect(review).toHaveTextContent("A mixed solver will take this.");
  expect(reviewNotes(d)).toEqual([
    "No rule or goal reads idle: the solver may set it to anything allowed.",
    "unused is declared but not read.",
    "staff has no maximum: if the goal rewards more of it, the answer may run to the platform's ceiling.",
  ]);
});
