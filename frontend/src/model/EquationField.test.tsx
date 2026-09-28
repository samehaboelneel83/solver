import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import EquationField, { chipsFor } from "./EquationField";
import { parseGoal } from "./formula";
import type { ModelContext } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["item"], setIds: {}, attributes: {}, relationships: [],
  variables: { x: { index: ["item"], domain: "integer" } },
  parameters: { cost: { index: ["item"] } },
};

function mount(onCommit = vi.fn()) {
  render(
    <EquationField label="Equation for o_cost" equation="x[i] * 1" parse={(t) => parseGoal(t, CONTEXT)}
      onCommit={onCommit} chips={chipsFor(CONTEXT)} sets={CONTEXT.sets} />,
  );
  return { field: screen.getByLabelText("Equation for o_cost") as HTMLTextAreaElement, onCommit };
}

it("inserts a name at the cursor, and commits only an equation that reads", () => {
  const { field, onCommit } = mount();
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: "sum(" } });
  field.setSelectionRange(4, 4);
  fireEvent.click(screen.getByRole("button", { name: "cost[item]" }));
  expect(field).toHaveValue("sum(cost[]");
  fireEvent.keyDown(field, { key: "Enter" });
  expect(onCommit).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: "sum(cost[i] * x[i] for i in item)" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(onCommit).toHaveBeenCalledWith(
    { sum: { mul: [{ par: "cost", index: ["i"] }, { var: "x", index: ["i"] }] }, over: [{ index: "i", set: "item" }] },
    "sum(cost[i] * x[i] for i in item)",
  );
});

it("puts the model's equation back on Escape", () => {
  const { field } = mount();
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: "nonsense +" } });
  expect(screen.getByRole("alert")).toBeInTheDocument();
  fireEvent.keyDown(field, { key: "Escape" });
  expect(field).toHaveValue("x[i] * 1");
});
