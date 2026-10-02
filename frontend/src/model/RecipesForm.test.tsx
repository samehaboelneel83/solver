import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import RecipesForm from "./RecipesForm";
import type { FormDraft } from "./draftIr";

const KINDS = [
  { name: "depot", attributes: [{ name: "capacity", data_type: "number" }, { name: "fixed_cost", data_type: "number" }] },
  { name: "store", attributes: [{ name: "demand", data_type: "integer" }] },
  { name: "project", attributes: [{ name: "benefit", data_type: "number" }, { name: "capex", data_type: "number" }, { name: "committed", data_type: "boolean" }] },
];
const empty: FormDraft = { sets: [], parameters: {}, variables: {}, constraints: [], objective: { sense: "minimize", mode: "weighted", terms: [] } };

it("writes projects-within-a-budget into the draft (benchmark, October 2026)", () => {
  const onApply = vi.fn();
  render(<RecipesForm kinds={KINDS} data={[]} onApply={onApply} />);
  fireEvent.change(screen.getByLabelText("Choose among"), { target: { value: "project" } });
  fireEvent.change(screen.getByLabelText("Worth"), { target: { value: "benefit" } });
  fireEvent.change(screen.getByLabelText("Cost"), { target: { value: "capex" } });
  const write = screen.getByRole("button", { name: "Write it into the model" });
  expect(write).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "1,000" } });
  fireEvent.change(screen.getByLabelText("Always chosen when"), { target: { value: "committed" } });
  fireEvent.click(write);
  const d = onApply.mock.calls[0][0](empty) as FormDraft;
  expect(d.constraints.map((c) => c.id)).toEqual(["budget", "must_have"]);
  expect(d.constraints[0]).toMatchObject({ right: { const: 1000 } });
  expect(screen.getByRole("status")).toHaveTextContent("Written into the model");
});

it("offers a network only with a cost a unit between the two kinds", () => {
  const onApply = vi.fn();
  const { rerender } = render(<RecipesForm kinds={KINDS} data={[]} onApply={onApply} />);
  fireEvent.click(screen.getByLabelText(/Supply network/));
  fireEvent.change(screen.getByLabelText("Ship from"), { target: { value: "depot" } });
  fireEvent.change(screen.getByLabelText("To"), { target: { value: "store" } });
  fireEvent.change(screen.getByLabelText("Each needs"), { target: { value: "demand" } });
  expect(screen.getByText(/No data value is indexed by both depot and store/)).toBeInTheDocument();
  rerender(<RecipesForm kinds={KINDS} data={[{ name: "km", index: ["store", "depot"] }]} onApply={onApply} />);
  fireEvent.change(screen.getByLabelText("Opening cost"), { target: { value: "fixed_cost" } });
  fireEvent.click(screen.getByRole("button", { name: "Write it into the model" }));
  const d = onApply.mock.calls[0][0](empty) as FormDraft;
  expect(Object.keys(d.variables)).toEqual(["ship", "open"]);
  expect(d.parameters.km).toEqual({ index: ["store", "depot"] });
});

it("shares land among crops from the form (benchmark re-test, October 2026)", () => {
  const onApply = vi.fn();
  const kinds = [{ name: "parcel", attributes: [{ name: "area", data_type: "number" }] },
    { name: "crop", attributes: [{ name: "profit", data_type: "number" }, { name: "water", data_type: "number" }] }];
  render(<RecipesForm kinds={kinds} data={[{ name: "suitable", index: ["parcel", "crop"] }]} onApply={onApply} />);
  fireEvent.click(screen.getByLabelText(/Share land among crops/));
  fireEvent.change(screen.getByLabelText("Share out each"), { target: { value: "parcel" } });
  fireEvent.change(screen.getByLabelText("Among"), { target: { value: "crop" } });
  fireEvent.change(screen.getByLabelText("Its size"), { target: { value: "area" } });
  fireEvent.change(screen.getByLabelText("A unit is worth"), { target: { value: "profit" } });
  fireEvent.change(screen.getByLabelText("Uses"), { target: { value: "water" } });
  fireEvent.change(screen.getByLabelText("Shared limit"), { target: { value: "100" } });
  fireEvent.change(screen.getByLabelText("Only where"), { target: { value: "suitable" } });
  fireEvent.click(screen.getByRole("button", { name: "Write it into the model" }));
  const d = onApply.mock.calls[0][0](empty) as FormDraft;
  expect(d.constraints.map((c) => c.id)).toEqual(["size_of_each", "shared_limit", "only_where_allowed"]);
});

it("routes trips over the roads from the form, the road's two ends read from the links' names (benchmark re-test, October 2026)", () => {
  const onApply = vi.fn();
  const kinds = [{ name: "junction", attributes: [] },
    { name: "road", attributes: [{ name: "minutes", data_type: "number" }, { name: "capacity", data_type: "number" }] }];
  const links = [{ name: "road_to", from: "road", to: "junction" }, { name: "road_from", from: "road", to: "junction" }];
  render(<RecipesForm kinds={kinds} data={[{ name: "trips", index: ["junction", "junction"] }]} links={links} onApply={onApply} />);
  fireEvent.click(screen.getByLabelText(/Traffic/));
  fireEvent.change(screen.getByLabelText("Trips between"), { target: { value: "junction" } });
  fireEvent.change(screen.getByLabelText("Over"), { target: { value: "road" } });
  expect(screen.getByLabelText("A road starts at")).toHaveValue("road_from");
  expect(screen.getByLabelText("and ends at")).toHaveValue("road_to");
  fireEvent.change(screen.getByLabelText("How many trips"), { target: { value: "trips" } });
  fireEvent.change(screen.getByLabelText("Time on a road"), { target: { value: "minutes" } });
  fireEvent.change(screen.getByLabelText("Capacity"), { target: { value: "capacity" } });
  fireEvent.click(screen.getByRole("button", { name: "Write it into the model" }));
  const d = onApply.mock.calls[0][0](empty) as FormDraft;
  expect(d.constraints.map((c) => c.id)).toEqual(["trips_arrive", "road_capacity"]);
  expect(JSON.stringify(d.constraints[0])).toContain('"via":{"rel":"road_to","to":"n"}');
});
