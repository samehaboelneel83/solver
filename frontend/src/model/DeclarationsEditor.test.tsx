import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DeclarationsEditor from "./DeclarationsEditor";
import type { Constraint, ObjectiveTerm, Term } from "./terms";

const CONSTRAINTS: Constraint[] = [
  {
    id: "c_cover",
    forall: [{ index: "d", set: "day" }],
    left: { sum: { var: "assign", index: ["e", "d"] }, over: [{ index: "e", set: "employee" }] },
    relation: ">=",
    right: { par: "demand", index: ["d"] },
    severity: "hard",
  } as Constraint,
];
const OBJECTIVE: ObjectiveTerm[] = [
  { id: "o_shifts", weight: 1, expression: { const: 0 } as Term },
];

function renderEditor(overrides: Partial<React.ComponentProps<typeof DeclarationsEditor>> = {}) {
  const onChange = vi.fn();
  render(
    <DeclarationsEditor
      sets={["employee", "day"]}
      parameters={{ demand: { index: ["day"] } }}
      variables={{ assign: { index: ["employee", "day"], domain: "binary" } }}
      entityTypeNames={["employee", "day", "shift"]}
      parameterOptions={[
        { name: "demand", index: ["day"] },
        { name: "cost", index: ["day", "shift"] },
      ]}
      constraints={CONSTRAINTS}
      objectiveTerms={OBJECTIVE}
      onChange={onChange}
      {...overrides}
    />
  );
  return onChange;
}

describe("DeclarationsEditor", () => {
  it("declares a set the domain has but the model does not yet", () => {
    const onChange = renderEditor();

    const setsCard = screen.getByRole("group", { name: "Sets" });
    fireEvent.click(within(setsCard).getByRole("checkbox", { name: "shift" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ sets: ["employee", "day", "shift"] }));
  });

  it("refuses to remove a set the rules still range over, naming them", () => {
    // The server refuses this too, but by then the edit is lost and the
    // message is about a document rather than about a rule.
    const onChange = renderEditor();

    const setsCard = screen.getByRole("group", { name: "Sets" });
    fireEvent.click(within(setsCard).getByRole("checkbox", { name: "day" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/day is used by c_cover/i);
  });

  it("refuses to remove a parameter a rule reads", () => {
    const onChange = renderEditor();

    fireEvent.click(screen.getByRole("checkbox", { name: /demand\[day\]/ }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/demand is used by c_cover/i);
  });

  it("removes a variable no rule mentions", () => {
    const onChange = renderEditor({
      variables: {
        assign: { index: ["employee", "day"], domain: "binary" },
        spare: { index: ["day"], domain: "integer" },
      },
    });

    fireEvent.click(screen.getAllByRole("button", { name: /remove/i })[1]);

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ variables: { assign: { index: ["employee", "day"], domain: "binary" } } })
    );
  });

  it("cannot declare a parameter whose index needs a set the model lacks", () => {
    // `cost[day, shift]` needs `shift`; without it no term could subscript
    // the parameter, so offering it would be offering a broken model.
    renderEditor();

    const cost = screen.getByRole("checkbox", { name: /cost\[day, shift\]/ });
    expect(cost).toBeDisabled();
    expect(screen.getByText(/shift.*is not a set of this model yet/i)).toBeInTheDocument();
  });

  it("offers that parameter as soon as the set it needs is declared", () => {
    renderEditor({ sets: ["employee", "day", "shift"] });

    expect(screen.getByRole("checkbox", { name: /cost\[day, shift\]/ })).toBeEnabled();
  });

  it("declares a parameter with the index its definition gives, not one typed here", () => {
    const onChange = renderEditor({ sets: ["employee", "day", "shift"], parameters: {} });

    fireEvent.click(screen.getByRole("checkbox", { name: /cost\[day, shift\]/ }));

    // Order matters: cost[day, shift] is not cost[shift, day], and that
    // mistake type-checks by arity.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ parameters: { cost: { index: ["day", "shift"] } } })
    );
  });

  it("adds a variable indexed by the sets chosen, in the order chosen", () => {
    const onChange = renderEditor();

    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "standby" } });
    const indexChoices = screen.getByRole("group", { name: /one for every/i });
    fireEvent.click(within(indexChoices).getByRole("checkbox", { name: /^day/ }));
    fireEvent.click(within(indexChoices).getByRole("checkbox", { name: /^employee/ }));
    fireEvent.click(screen.getByRole("button", { name: /add variable/i }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        variables: expect.objectContaining({ standby: { index: ["day", "employee"], domain: "binary" } }),
      })
    );
  });

  it("refuses a name the database would refuse anyway", () => {
    renderEditor();

    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "Standby" } });

    expect(screen.getByRole("alert")).toHaveTextContent(/lower-case/i);
    expect(screen.getByRole("button", { name: /add variable/i })).toBeDisabled();
  });

  it("refuses a name already taken by a parameter", () => {
    renderEditor();

    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "demand" } });

    expect(screen.getByRole("alert")).toHaveTextContent(/already something called demand/i);
  });

  it("will not add a variable with no index, and says why", () => {
    renderEditor();

    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "standby" } });

    expect(screen.getByRole("button", { name: /add variable/i })).toBeDisabled();
    expect(screen.getByText(/a variable with no index is a single number/i)).toBeInTheDocument();
  });
});
