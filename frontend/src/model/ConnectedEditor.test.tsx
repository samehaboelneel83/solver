import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import ConnectedEditor from "./ConnectedEditor";
import { checkIrShape } from "../ir/validate";
import { connectedChoices, declaredRelationships, describeConnected, newConnectedRule, type Constraint, type ModelContext } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["cell", "zone", "employee"],
  setIds: {},
  attributes: {},
  variables: {
    assign: { index: ["cell", "zone"], domain: "binary" },
    sub: { index: ["cell", "cell"], domain: "binary" },
    hours: { index: ["employee", "zone"], domain: "integer" },
    staff: { index: ["employee", "zone"], domain: "binary" },
  },
  parameters: {},
  relationships: [
    { name: "adjacent", from: "cell", to: "cell" },
    { name: "near", from: "cell", to: "cell" },
    { name: "works_in", from: "employee", to: "zone" },
  ],
};

function Harness({ start }: { start: Constraint }) {
  const [rule, setRule] = useState<Constraint>(start);
  return (
    <>
      <ConnectedEditor constraint={rule} onChange={setRule} context={CONTEXT} />
      <output data-testid="rule">{JSON.stringify(rule)}</output>
    </>
  );
}

const shown = () => JSON.parse(screen.getByTestId("rule").textContent!) as Constraint;

describe("the connected rule's choices", () => {
  it("are yes-or-no variables over two different sets, with the relationships joining the first to itself", () => {
    expect(connectedChoices(CONTEXT)).toEqual([
      { variable: "assign", units: "cell", groups: "zone", vias: ["adjacent", "near"] },
      { variable: "staff", units: "employee", groups: "zone", vias: [] },
    ]);
  });

  it("start from the first variable that has a relationship, and make a valid rule", () => {
    const rule = newConnectedRule("c_1", CONTEXT)!;
    expect(rule).toEqual({
      id: "c_1",
      severity: "hard",
      connected: {
        assign: { var: "assign", index: ["c", "z"] },
        units: { index: "c", set: "cell" },
        groups: { index: "z", set: "zone" },
        via: "adjacent",
        empty: "forbidden",
      },
    });
    const ir = {
      version: 2, sets: ["cell", "zone"], relationships: declaredRelationships([rule], []), parameters: {},
      variables: { assign: { index: ["cell", "zone"], domain: "binary" } }, constraints: [rule],
    };
    expect(checkIrShape(ir)).toBeNull();
  });

  it("are none when no relationship joins a variable's first set to itself", () => {
    expect(newConnectedRule("c_1", { ...CONTEXT, relationships: [CONTEXT.relationships[2]] })).toBeNull();
  });

  it("never name both indices alike", () => {
    const rule = newConnectedRule("c_1", {
      ...CONTEXT,
      variables: { pick: { index: ["zone", "zeta"], domain: "binary" } },
      relationships: [{ name: "touches", from: "zone", to: "zone" }],
    })!;
    expect(rule.connected!.assign.index).toEqual(["z", "z2"]);
  });
});

describe("ConnectedEditor", () => {
  it("offers only admissible choices and writes what it shows", () => {
    render(<Harness start={newConnectedRule("c_1", CONTEXT)!} />);
    const variable = screen.getByLabelText("Assignment") as HTMLSelectElement;
    expect([...variable.options].map((o) => o.value)).toEqual(["assign", "staff"]);
    const via = screen.getByLabelText("Connected over") as HTMLSelectElement;
    expect([...via.options].map((o) => o.value)).toEqual(["adjacent", "near"]);
    fireEvent.change(via, { target: { value: "near" } });
    fireEvent.click(screen.getByLabelText(/may be left with no cell/));
    expect(shown().connected).toMatchObject({ via: "near", empty: "allowed" });
    expect(screen.getByText("each zone is one connected piece of cell (or empty) over near")).toBeInTheDocument();
  });

  it("says so when the variable chosen has no relationship to be one piece over", () => {
    render(<Harness start={newConnectedRule("c_1", CONTEXT)!} />);
    fireEvent.change(screen.getByLabelText("Assignment"), { target: { value: "staff" } });
    expect(shown().connected).toMatchObject({ assign: { var: "staff", index: ["e", "z"] }, via: "" });
    expect(screen.getByRole("option", { name: "no relationship joins employee to itself" })).toBeInTheDocument();
  });

  it("keeps the rule hard, whatever the draft carried", () => {
    const start = { ...newConnectedRule("c_1", CONTEXT)!, severity: "soft", weight: 4 } as Constraint;
    render(<Harness start={start} />);
    fireEvent.change(screen.getByLabelText("Connected over"), { target: { value: "near" } });
    expect(shown()).toMatchObject({ severity: "hard" });
    expect(shown().weight).toBeUndefined();
  });

  it("reads back in words", () => {
    expect(describeConnected({ connected: { units: { set: "cell" }, groups: { set: "zone" }, via: "adjacent" } })).toBe(
      "each zone is one connected piece of cell over adjacent"
    );
    expect(describeConnected({})).toBeNull();
  });
});
