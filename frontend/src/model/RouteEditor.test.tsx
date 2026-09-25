import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import RouteEditor from "./RouteEditor";
import { describeRoute, newRouteRule, routeChoices, type Constraint, type ModelContext } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["truck", "stop"],
  setIds: { truck: 1, stop: 2 },
  attributes: { truck: [{ name: "capacity", data_type: "integer" }], stop: [{ name: "demand", data_type: "integer" }] },
  variables: {
    visit: { index: ["truck", "stop", "stop"], domain: "binary" },
    assign: { index: ["stop", "truck"], domain: "binary" },
  },
  parameters: {},
  relationships: [],
};

function Harness({ start }: { start: Constraint }) {
  const [rule, setRule] = useState(start);
  return (
    <>
      <RouteEditor constraint={rule} context={CONTEXT} onChange={setRule} />
      <pre data-testid="rule">{JSON.stringify(rule)}</pre>
    </>
  );
}
const shown = () => JSON.parse(screen.getByTestId("rule").textContent ?? "{}") as Constraint;

describe("the route rule's choices (queue R15b)", () => {
  it("offers only a yes-or-no over vehicle x stop x stop, indices named after their sets", () => {
    expect(routeChoices(CONTEXT)).toEqual([{ variable: "visit", vehicles: "truck", stops: "stop" }]);
    const rule = newRouteRule("c_1", CONTEXT)!;
    expect(rule.route).toEqual({
      visit: { var: "visit", index: ["t", "s", "s_next"] },
      vehicles: { index: "t", set: "truck" },
      stops: { index: "s", set: "stop" },
      depot: "depot",
    });
    expect(describeRoute(rule)).toBe("every stop but depot visited once by a truck from depot and back");
  });

  it("names a depot and turns loads on and off, always hard", () => {
    render(<Harness start={{ ...newRouteRule("c_1", CONTEXT)!, severity: "soft", weight: 3 } as Constraint} />);
    fireEvent.change(screen.getByLabelText(/Depot/), { target: { value: "hub" } });
    expect(shown().route!.depot).toBe("hub");
    expect(shown().severity).toBe("hard");
    expect(shown().weight).toBeUndefined();
    fireEvent.click(screen.getByLabelText(/carries a load/));
    expect(shown().route).toMatchObject({ demand: "demand", capacity: "capacity" });
    expect(screen.getByText("every stop but hub visited once by a truck from hub and back, demand within truck capacity")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/carries a load/));
    expect(shown().route!.demand).toBeUndefined();
  });
});
