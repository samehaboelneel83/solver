import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import GoalBreakdown from "./GoalBreakdown";

it("shows each goal term's value, its share and the records it comes from (benchmark, October 2026)", () => {
  render(<GoalBreakdown breakdown={{ sense: "minimize", mode: "weighted", terms: [
    { id: "shipping_cost", weight: 1, value: 70, contribution: 70, share: 0.4268, records: [{ kind: "depot", key: "south", value: 70 }] },
    { id: "opening_cost", weight: 1, value: 80, contribution: 80, share: 0.4878, records: [{ kind: "depot", key: "south", value: 80 }],
      rest: { records: 3, value: 5 } },
  ] }} labels={{ "depot:south": "South depot" }} />);
  const table = screen.getByRole("table", { name: "Goal by term" });
  expect(table).toHaveTextContent("shipping cost");
  expect(table).toHaveTextContent("48.8%");
  expect(table).toHaveTextContent("South depot 80");
  expect(table).toHaveTextContent("3 others 5");
});

it("says nothing for a single term from a single record", () => {
  const { container } = render(<GoalBreakdown breakdown={{ sense: "minimize", mode: "weighted",
    terms: [{ id: "cost", weight: 1, value: 3, contribution: 3, share: 1, records: [{ kind: "", key: "", value: 3 }] }] }} />);
  expect(container).toBeEmptyDOMElement();
});
