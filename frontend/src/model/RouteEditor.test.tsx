import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import RouteEditor from "./RouteEditor";
import { declaredRelationships, describeRoute, newRouteRule, routeChoices, type Constraint, type ModelContext } from "./terms";

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

describe("time windows on the route rule (queue R15c)", () => {
  const timed: ModelContext = {
    ...CONTEXT,
    attributes: { ...CONTEXT.attributes, stop: [{ name: "open", data_type: "integer" }, { name: "close", data_type: "integer" }] },
    parameters: { minutes: { index: ["stop", "stop"] }, cost: { index: ["truck"] } },
  };
  function TimedHarness({ start }: { start: Constraint }) {
    const [rule, setRule] = useState(start);
    return (
      <>
        <RouteEditor constraint={rule} context={timed} onChange={setRule} />
        <pre data-testid="rule">{JSON.stringify(rule)}</pre>
      </>
    );
  }

  it("names the travel time from a stop-to-stop table and the window from the stops' numbers", () => {
    render(<TimedHarness start={newRouteRule("c_1", timed)!} />);
    fireEvent.click(screen.getByLabelText(/has a time window/));
    expect(shown().route).toMatchObject({ travel: "minutes", earliest: "open", latest: "close" });
    // Only a table over [stop, stop] is a travel time.
    expect([...(screen.getByLabelText("Travel time") as HTMLSelectElement).options].map((o) => o.value)).toEqual(["minutes"]);
    fireEvent.change(screen.getByLabelText("Open until"), { target: { value: "" } });
    expect(shown().route).not.toHaveProperty("latest");
    expect(describeRoute(shown())).toMatch(/arriving between open and any time after minutes$/);
    fireEvent.click(screen.getByLabelText(/has a time window/));
    expect(shown().route).not.toHaveProperty("travel");
  });

  it("cannot be switched on without a stop-to-stop table", () => {
    render(<Harness start={newRouteRule("c_1", CONTEXT)!} />);
    expect(screen.getByLabelText(/has a time window/)).toBeDisabled();
  });

  it("lets each vehicle start from its own depot, named by one of its fields (benchmark, October 2026)", () => {
    const context = { ...CONTEXT, attributes: { ...CONTEXT.attributes, truck: [...CONTEXT.attributes.truck, { name: "home", data_type: "reference" }] } };
    function Own() {
      const [rule, setRule] = useState(newRouteRule("c_1", context)!);
      return <><RouteEditor constraint={rule} context={context} onChange={setRule} /><pre data-testid="rule">{JSON.stringify(rule)}</pre></>;
    }
    render(<Own />);
    fireEvent.change(screen.getByLabelText("Where vehicles start"), { target: { value: "own" } });
    const route = shown().route!;
    expect(route.depot).toBeUndefined();
    expect(route.depot_of).toBe("home");
    expect(describeRoute(shown())).toBe("every stop but the depots visited once by a truck from its own home and back");
    fireEvent.change(screen.getByLabelText("Where vehicles start"), { target: { value: "one" } });
    expect(shown().route).toMatchObject({ depot: "depot" });
    expect(shown().route!.depot_of).toBeUndefined();
  });

  it("lets each vehicle start where an earlier plan placed it, by a relationship either way (benchmark re-test, October 2026)", () => {
    const context = { ...CONTEXT, relationships: [...CONTEXT.relationships, { name: "placed_at", from: "stop", to: "truck" }] } as ModelContext;
    function Linked() {
      const [rule, setRule] = useState(newRouteRule("c_1", context)!);
      return <><RouteEditor constraint={rule} context={context} onChange={setRule} /><pre data-testid="rule">{JSON.stringify(rule)}</pre></>;
    }
    render(<Linked />);
    fireEvent.change(screen.getByLabelText("Where vehicles start"), { target: { value: "linked" } });
    expect(shown().route).toMatchObject({ depot_by: "placed_at" });
    expect(shown().route!.depot).toBeUndefined();
    expect(describeRoute(shown())).toBe("every stop but the depots visited once by a truck from the stop it is linked to by placed_at and back");
    expect(declaredRelationships([shown()], [])).toEqual(["placed_at"]);
  });
});
