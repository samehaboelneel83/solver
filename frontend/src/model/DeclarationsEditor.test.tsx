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

  it("shows an interval by its parts, and never turns an existing variable into one", () => {
    renderEditor({
      variables: {
        assign: { index: ["employee", "day"], domain: "binary" },
        task: { index: ["day"], domain: "interval", start: "b", end: "e", size: "demand", presence: "on" },
      },
    });
    expect(screen.getByText(/task is a span of time: from b to e, lasting demand, and only if on/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("task decides")).not.toBeInTheDocument();
    const picker = screen.getByLabelText("assign decides") as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(["binary", "integer", "continuous"]);
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

  it("names continuous separately from a whole number, not as the same choice twice", () => {
    renderEditor();

    const decides = screen.getByLabelText(/^decides$/i) as HTMLSelectElement;
    expect(Array.from(decides.options).map((o) => o.textContent)).toEqual([
      "yes or no",
      "a whole number",
      "any number",
      "a span of time",
    ]);
  });

  it("makes a new interval whole: its start and end are declared with it", () => {
    const onChange = renderEditor();
    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "shift_block" } });
    fireEvent.change(screen.getByLabelText(/^decides$/i), { target: { value: "interval" } });
    const indexChoices = screen.getByRole("group", { name: /one for every/i });
    fireEvent.click(within(indexChoices).getByRole("checkbox", { name: /^day/ }));
    fireEvent.click(screen.getByRole("button", { name: /add variable/i }));

    const variables = onChange.mock.calls.at(-1)![0].variables;
    expect(variables.shift_block).toEqual({
      index: ["day"], domain: "interval", start: "shift_block_start", end: "shift_block_end", size: 1,
    });
    expect(variables.shift_block_start).toEqual({ index: ["day"], domain: "integer", lower: 0 });
    expect(variables.shift_block_end).toEqual({ index: ["day"], domain: "integer", lower: 0 });
  });

  it("edits an interval's parts from declarations over its own sets", () => {
    const onChange = renderEditor({
      parameters: { demand: { index: ["day"] } },
      variables: {
        assign: { index: ["employee", "day"], domain: "binary" },
        on: { index: ["day"], domain: "binary" },
        b: { index: ["day"], domain: "integer" },
        e: { index: ["day"], domain: "integer" },
        wrong_index: { index: ["employee"], domain: "integer" },
        task: { index: ["day"], domain: "interval", start: "b", end: "e", size: 3 },
      },
    });
    const starts = screen.getByLabelText("task starts at") as HTMLSelectElement;
    expect(Array.from(starts.options).map((o) => o.value)).toEqual(["b", "e"]);

    fireEvent.change(screen.getByLabelText("task lasts"), { target: { value: "demand" } });
    expect(onChange.mock.calls.at(-1)![0].variables.task.size).toBe("demand");

    fireEvent.change(screen.getByLabelText("task happens"), { target: { value: "on" } });
    expect(onChange.mock.calls.at(-1)![0].variables.task.presence).toBe("on");
  });

  it("refuses to remove a variable an interval is built from, naming the interval", () => {
    renderEditor({
      variables: {
        assign: { index: ["employee", "day"], domain: "binary" },
        b: { index: ["day"], domain: "integer" },
        e: { index: ["day"], domain: "integer" },
        task: { index: ["day"], domain: "interval", start: "b", end: "e", size: 3 },
      },
    });
    const card = screen.getByText("b[day]").closest("div")!.parentElement!;
    fireEvent.click(within(card).getByRole("button", { name: /remove/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/b is used by task/);
  });

  it("says a continuous variable decides any number, not a whole number", () => {
    renderEditor({
      variables: { flow: { index: ["day"], domain: "continuous" } },
    });

    expect(screen.getByLabelText(/flow decides/i)).toHaveValue("continuous");
    const decides = screen.getByLabelText(/flow decides/i) as HTMLSelectElement;
    expect(decides.options[decides.selectedIndex]?.textContent).toBe("any number");
  });

  it("adds a continuous variable when that is what was chosen", () => {
    const onChange = renderEditor();

    fireEvent.change(screen.getByLabelText(/new variable/i), { target: { value: "flow" } });
    fireEvent.change(screen.getByLabelText(/^decides$/i), { target: { value: "continuous" } });
    fireEvent.click(within(screen.getByRole("group", { name: /one for every/i })).getByRole("checkbox", { name: /^day/ }));
    fireEvent.click(screen.getByRole("button", { name: /add variable/i }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        variables: expect.objectContaining({ flow: { index: ["day"], domain: "continuous" } }),
      })
    );
  });

  it("can change what an existing variable decides", () => {
    const onChange = renderEditor({
      variables: { assign: { index: ["employee", "day"], domain: "binary" } },
    });

    fireEvent.change(screen.getByLabelText(/assign decides/i), { target: { value: "continuous" } });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        variables: { assign: { index: ["employee", "day"], domain: "continuous" } },
      })
    );
  });

  it("offers bounds only when the variable is not yes-or-no", () => {
    const { rerender } = render(
      <DeclarationsEditor
        sets={["day"]}
        parameters={{}}
        variables={{ hours: { index: ["day"], domain: "binary" } }}
        entityTypeNames={["day"]}
        parameterOptions={[]}
        constraints={[]}
        objectiveTerms={[]}
        onChange={vi.fn()}
      />
    );
    expect(screen.queryByLabelText(/hours no less than/i)).not.toBeInTheDocument();

    rerender(
      <DeclarationsEditor
        sets={["day"]}
        parameters={{}}
        variables={{ hours: { index: ["day"], domain: "integer" } }}
        entityTypeNames={["day"]}
        parameterOptions={[]}
        constraints={[]}
        objectiveTerms={[]}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByLabelText(/hours no less than/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/hours no more than/i)).toBeInTheDocument();
  });

  it("writes a lower bound and drops it again when the variable becomes yes-or-no", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <DeclarationsEditor
        sets={["day"]}
        parameters={{}}
        variables={{ hours: { index: ["day"], domain: "integer" } }}
        entityTypeNames={["day"]}
        parameterOptions={[]}
        constraints={[]}
        objectiveTerms={[]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByLabelText(/hours no less than/i), { target: { value: "0" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        variables: { hours: { index: ["day"], domain: "integer", lower: 0 } },
      })
    );

    rerender(
      <DeclarationsEditor
        sets={["day"]}
        parameters={{}}
        variables={{ hours: { index: ["day"], domain: "integer", lower: 0 } }}
        entityTypeNames={["day"]}
        parameterOptions={[]}
        constraints={[]}
        objectiveTerms={[]}
        onChange={onChange}
      />
    );
    fireEvent.change(screen.getByLabelText(/hours decides/i), { target: { value: "binary" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        variables: { hours: { index: ["day"], domain: "binary" } },
      })
    );
  });

  it("says when no less than is above no more than", () => {
    renderEditor({
      variables: { hours: { index: ["day"], domain: "integer", lower: 10, upper: 5 } },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/no less than 10 is above no more than 5/i);
  });
});

describe("DeclarationsEditor and an uncertain parameter", () => {
  it("declares a range as a fraction, with an optional cap, and exact removes it", () => {
    const onChange = renderEditor();
    fireEvent.change(screen.getByLabelText(/demand.s values are/i), { target: { value: "interval" } });
    expect(onChange.mock.calls.at(-1)![0].parameters.demand).toEqual({
      index: ["day"],
      uncertainty: { kind: "interval", deviation: 0.1 },
    });
  });

  it("reads a range back as a percentage, and edits its share and its cap", () => {
    const onChange = renderEditor({
      parameters: { demand: { index: ["day"], uncertainty: { kind: "interval", deviation: 0.25 } } },
    });
    const share = screen.getByLabelText(/demand may be off by up to/i) as HTMLInputElement;
    expect(share.value).toBe("25");
    fireEvent.change(share, { target: { value: "12.5" } });
    expect(onChange.mock.calls.at(-1)![0].parameters.demand.uncertainty).toEqual({ kind: "interval", deviation: 0.125 });
    fireEvent.change(screen.getByLabelText(/at most this many/i), { target: { value: "2" } });
    expect(onChange.mock.calls.at(-1)![0].parameters.demand.uncertainty).toEqual({
      kind: "interval",
      deviation: 0.25,
      gamma: 2,
    });
  });

  it("takes one value per scenario, and exact writes nothing", () => {
    const onChange = renderEditor({
      parameters: { demand: { index: ["day"], uncertainty: { kind: "interval", deviation: 0.1 } } },
    });
    const kind = screen.getByLabelText(/demand.s values are/i);
    fireEvent.change(kind, { target: { value: "scenarios" } });
    expect(onChange.mock.calls.at(-1)![0].parameters.demand).toEqual({
      index: ["day"],
      uncertainty: {
        kind: "scenarios",
        futures: [
          { label: "low", factor: 0.8 },
          { label: "high", factor: 1.2 },
        ],
      },
    });
    fireEvent.change(kind, { target: { value: "exact" } });
    expect(onChange.mock.calls.at(-1)![0].parameters.demand).toEqual({ index: ["day"] });
  });
});

describe("declarations in the four views", () => {
  const VARS = {
    assign: { index: ["employee", "day"], domain: "binary" as const },
    overtime: { index: ["employee"], domain: "continuous" as const, lower: 0, upper: 20 },
  };

  it("reads every set, parameter and variable as a sentence, with what reads it", () => {
    renderEditor({ variables: VARS, attributes: { employee: [{ name: "cap", data_type: "number" }, { name: "team", data_type: "text" }] }, units: { demand: "staff" } });
    fireEvent.click(screen.getByRole("button", { name: "Show all declarations as sentences" }));
    const sentences = screen.getAllByTestId("declaration-sentence").map((node) => node.querySelector("p")!.textContent);
    expect(sentences).toEqual([
      "The rules can range over every employee record of this domain. Each employee has the number cap. Read by c_cover.",
      "The rules can range over every day record of this domain. Read by c_cover.",
      "demand is data the domain holds: one number for every day, in staff. Read by c_cover.",
      "The solver decides assign for every employee and every day: yes or no. Read by c_cover.",
      "The solver decides overtime for every employee: any number from 0 to 20. No rule or goal reads it yet.",
    ]);
  });

  it("changes a variable's kind and limits in its boxes", () => {
    const onChange = renderEditor({ variables: VARS });
    fireEvent.click(screen.getByRole("button", { name: "Show overtime as boxes" }));
    const blocks = screen.getByTestId("declaration-blocks");
    expect(within(blocks).getByRole("group", { name: "For each: one for every" })).toHaveTextContent("employee");
    fireEvent.change(within(blocks).getByLabelText("overtime: at most"), { target: { value: "" } });
    expect(onChange.mock.calls.at(-1)![0].variables.overtime).toEqual({ index: ["employee"], domain: "continuous", lower: 0 });
    fireEvent.change(within(blocks).getByLabelText("overtime: kind"), { target: { value: "integer" } });
    expect(onChange.mock.calls.at(-1)![0].variables.overtime.domain).toBe("integer");
  });

  it("writes a variable's limits from its equation, and refuses a new name there", () => {
    const onChange = renderEditor({ variables: VARS });
    const field = screen.getByLabelText("Equation for overtime") as HTMLTextAreaElement;
    expect(field.value).toBe("0 <= overtime[employee] <= 20, continuous");
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "2 <= overtime[employee] <= 10, integer" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onChange.mock.calls.at(-1)![0].variables.overtime).toEqual({ index: ["employee"], domain: "integer", lower: 2, upper: 10 });
    fireEvent.change(field, { target: { value: "0 <= extra[employee], integer" } });
    expect(screen.getByText(/to make “extra”, add a new variable/)).toBeInTheDocument();
    expect(screen.getByLabelText("Equation for assign")).toHaveValue("assign[employee, day] in {0, 1}");
  });

  it("draws a declaration as a diagram of its parts and readers", () => {
    renderEditor({ variables: VARS });
    fireEvent.click(screen.getByRole("button", { name: "Show all declarations as diagrams" }));
    const diagrams = screen.getAllByTestId("declaration-diagram");
    expect(diagrams).toHaveLength(5);
    expect(diagrams[4]).toHaveTextContent(/overtimedecision.*every employeeone for.*any numberkind.*at least 0range.*at most 20range.*read bynothing yet/);
  });
});
