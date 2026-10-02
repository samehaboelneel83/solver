import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import DescribeToDraft from "./DescribeToDraft";
import type { FormDraft } from "./draftIr";

const KINDS = [{ name: "project", attributes: [{ name: "benefit", data_type: "number" }, { name: "capex", data_type: "number" }] }];
const empty: FormDraft = { sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } };

it("proposes a draft from the words, says what is missing, and writes it when asked", () => {
  const onApply = vi.fn();
  render(<DescribeToDraft kinds={KINDS} data={[]} onApply={onApply} startOpen />);
  const words = screen.getByLabelText("The problem in words");
  fireEvent.change(words, { target: { value: "Which projects should we fund this time" } });
  expect(screen.getByRole("heading", { name: "Choose projects within a budget" })).toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent(/the budget/);
  expect(screen.getByRole("button", { name: "Write this draft into the model" })).toBeDisabled();
  fireEvent.change(words, { target: { value: "Which projects should we fund with a budget of 900" } });
  fireEvent.click(screen.getByRole("button", { name: "Write this draft into the model" }));
  const d = onApply.mock.calls[0][0](empty) as FormDraft;
  expect(d.variables.choose).toEqual({ index: ["project"], domain: "binary" });
  expect(screen.getByRole("status")).toHaveTextContent("Written below");
});
