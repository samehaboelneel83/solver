import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TermBuilder from "./TermBuilder";
import { printTerm } from "./formula";
import { degree, describeTerm, termKind, type Binding, type ModelContext, type Term } from "./terms";

/** Epic ML: a trained model's prediction, as the editor reads and shows it. */

const CONTEXT: ModelContext = {
  sets: ["store"],
  setIds: { store: 1 },
  attributes: { store: [{ name: "footfall", data_type: "number" }] },
  variables: { price: { index: ["store"], domain: "continuous" } },
  parameters: {},
  relationships: [],
};
const BOUND: Binding[] = [{ index: "s", set: "store" }];

const OF_DECISIONS = {
  predict: "sales_model",
  of: [{ var: "price", index: ["s"] }, { attr: { of: "s", name: "footfall" } }],
} as Term;
const OF_DATA = { predict: "sales_model", of: [{ const: 4 }, { const: 300 }] } as Term;

describe("a predict term", () => {
  it("is its own kind, read back as the model applied to its inputs", () => {
    expect(termKind(OF_DECISIONS)).toBe("predict");
    expect(describeTerm(OF_DECISIONS)).toBe("predict sales_model(price[s], footfall[s])");
    expect(printTerm(OF_DECISIONS)).toBe("predict sales_model(price[s], footfall[s])");
  });

  it("stands for a decision when an input reads one, and is a number of data", () => {
    expect(degree(OF_DECISIONS)).toBe(1);
    expect(degree(OF_DATA)).toBe(0);
  });

  it("shows each input as a term to edit, and is never offered to be minted", () => {
    render(<TermBuilder value={OF_DECISIONS} onChange={vi.fn()} context={CONTEXT} bound={BOUND} />);
    expect(screen.getByText("Input 1")).toBeInTheDocument();
    expect(screen.getByText("Input 2")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/sales_model/);

    const { container } = render(<TermBuilder value={{ const: 1 }} onChange={vi.fn()} context={CONTEXT} bound={BOUND} />);
    const picker = within(container).getAllByRole("combobox")[0];
    expect(within(picker).queryByText("a trained model's prediction")).toBeNull();
  });
});
