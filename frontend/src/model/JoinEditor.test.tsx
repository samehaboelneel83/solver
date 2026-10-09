import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import JoinEditor from "./JoinEditor";
import { checkIrShape } from "../ir/validate";
import { declaredRelationships, describeJoin, joinChoices, newJoinRule, type Constraint, type ModelContext } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["site", "segment"],
  setIds: {},
  attributes: {
    site: [{ name: "is_exchange", data_type: "boolean" }, { name: "name", data_type: "text" }, { name: "homes", data_type: "integer" }],
    segment: [{ name: "fibres", data_type: "integer" }],
  },
  variables: {
    lay: { index: ["segment"], domain: "binary" },
    serve: { index: ["site"], domain: "binary" },
    flow: { index: ["segment"], domain: "integer" },
    used: { index: ["site"], domain: "integer" },
  },
  parameters: {},
  relationships: [
    { name: "seg_a", from: "segment", to: "site" },
    { name: "seg_b", from: "segment", to: "site" },
    { name: "near", from: "site", to: "site" },
  ],
};

function Harness({ start }: { start: Constraint }) {
  const [rule, setRule] = useState<Constraint>(start);
  return (
    <>
      <JoinEditor constraint={rule} onChange={setRule} context={CONTEXT} />
      <output data-testid="rule">{JSON.stringify(rule)}</output>
    </>
  );
}

const shown = () => JSON.parse(screen.getByTestId("rule").textContent!) as Constraint;

describe("the join rule", () => {
  it("offers yes-or-no links with two relationships to the places, and makes a valid rule", () => {
    expect(joinChoices(CONTEXT)).toEqual([
      { build: "lay", links: "segment", places: "site", ends: ["seg_a", "seg_b"], uses: ["serve"] },
    ]);
    const rule = newJoinRule("c_1", CONTEXT)!;
    expect(rule.join).toEqual({
      links: { index: "s", set: "segment" }, build: { var: "lay", index: ["s"] }, ends: ["seg_a", "seg_b"],
      places: { index: "s2", set: "site" },
    });
    const ir = {
      version: 2, sets: ["site", "segment"], relationships: declaredRelationships([rule], []), parameters: {},
      variables: { lay: { index: ["segment"], domain: "binary" } }, constraints: [rule],
      objective: { sense: "minimize", terms: [{ id: "o", weight: 1, expression: { const: 0 } }] },
    };
    expect(ir.relationships).toEqual(["seg_a", "seg_b"]);
    expect(checkIrShape(ir)).toBeNull();
    expect(describeJoin(rule)).toBe("the segment with lay = 1 join every site into one network");
  });

  it("chooses the places to join and the sources in the form", () => {
    render(<Harness start={newJoinRule("c_1", CONTEXT)!} />);
    fireEvent.change(screen.getByLabelText("Places to join"), { target: { value: "serve" } });
    fireEvent.change(screen.getByLabelText("Joined to (sources)"), { target: { value: "is_exchange" } });
    const rule = shown();
    expect(rule.join?.use).toEqual({ var: "serve", index: ["s2"] });
    expect(rule.join?.sources).toBe("is_exchange");
    expect(rule.severity).toBe("hard");
    expect(screen.getByText(/join every site with serve = 1 to a source \(is_exchange\)/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Places to join"), { target: { value: "" } });
    expect(shown().join?.use).toBeUndefined();
  });

  it("carries what each place takes, within each link's capacity, once there are sources", () => {
    render(<Harness start={newJoinRule("c_1", CONTEXT)!} />);
    expect(screen.queryByLabelText("Each place takes")).toBeNull();
    fireEvent.change(screen.getByLabelText("Joined to (sources)"), { target: { value: "is_exchange" } });
    fireEvent.change(screen.getByLabelText("Each place takes"), { target: { value: "homes" } });
    fireEvent.change(screen.getByLabelText("A link carries at most"), { target: { value: "fibres" } });
    fireEvent.change(screen.getByLabelText("What each link carries, in"), { target: { value: "flow" } });
    const rule = shown();
    expect(rule.join).toMatchObject({ demand: "homes", capacity: "fibres", carry: { var: "flow", index: ["s"] } });
    expect(screen.getByText(/carrying each its homes within each link's fibres \(flow per link\)/)).toBeTruthy();
    const ir = {
      version: 2, sets: ["site", "segment"], relationships: declaredRelationships([rule], []), parameters: {},
      variables: { lay: { index: ["segment"], domain: "binary" }, flow: { index: ["segment"], domain: "integer" } },
      constraints: [rule], objective: { sense: "minimize", terms: [{ id: "o", weight: 1, expression: { const: 0 } }] },
    };
    expect(checkIrShape(ir)).toBeNull();
    fireEvent.change(screen.getByLabelText("Joined to (sources)"), { target: { value: "" } });
    expect(shown().join).not.toHaveProperty("demand");
    expect(shown().join).not.toHaveProperty("carry");
  });
});
