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
  expect(table).toHaveTextContent("South depot " + (80).toLocaleString(undefined, { maximumSignificantDigits: 6 }));
  expect(table).toHaveTextContent("3 others " + (5).toLocaleString(undefined, { maximumSignificantDigits: 6 }));
});

it("shows a weighted term's own value and what it counts in the goal (benchmark round 3)", () => {
  render(<GoalBreakdown breakdown={{ sense: "maximize", mode: "weighted", terms: [
    { id: "profit", weight: 1, value: 86, contribution: 86, share: 0.9, records: [] },
    { id: "water_use", weight: -0.5, value: 20, contribution: -10, share: 0.1, records: [] },
  ] }} />);
  const row = screen.getByRole("row", { name: /water use/ });
  expect(row).toHaveTextContent("water use × " + (-0.5).toLocaleString(undefined, { maximumSignificantDigits: 6 }));
  expect(row.querySelectorAll("td")[1]).toHaveTextContent((20).toLocaleString());
  expect(row.querySelectorAll("td")[2]).toHaveTextContent((-10).toLocaleString());
});

it("says nothing for a single term from a single record", () => {
  const { container } = render(<GoalBreakdown breakdown={{ sense: "minimize", mode: "weighted",
    terms: [{ id: "cost", weight: 1, value: 3, contribution: 3, share: 1, records: [{ kind: "", key: "", value: 3 }] }] }} />);
  expect(container).toBeEmptyDOMElement();
});

it("shows goals solved in order by their place, with no share of one sum (benchmark round 4)", () => {
  render(<GoalBreakdown breakdown={{ sense: "maximize", mode: "lex", terms: [
    { id: "people_covered", weight: 1, value: 23900, contribution: 23900, share: null, records: [] },
    { id: "cost", weight: -1, value: 76100, contribution: -76100, share: null, records: [] },
  ] }} />);
  const table = screen.getByRole("table", { name: "Goal by term" });
  expect(table).not.toHaveTextContent("%");
  expect(table).not.toHaveTextContent("Share");
  expect(screen.getByRole("row", { name: /cost/ })).toHaveTextContent("2nd");
  expect(screen.getByRole("row", { name: /cost/ })).not.toHaveTextContent("×");
});
