import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeneratedSetsEditor } from "./GeneratedSetsEditor";

const TYPES = [
  { name: "area", attributes: [{ name: "shape" }, { name: "zone" }] },
  { name: "item_kind", attributes: [{ name: "length_cells" }, { name: "width_cells" }, { name: "can_turn" }, { name: "value" }] },
  { name: "nurse", attributes: [{ name: "ward" }] },
  { name: "shift", attributes: [{ name: "ward" }] },
];

function mount(generate: Record<string, unknown>[] = []) {
  const onChange = vi.fn();
  render(<GeneratedSetsEditor generate={generate} sets={["area", "item_kind", "nurse", "shift"]} relationships={["can_work"]}
    types={TYPES} canEdit onChange={onChange} />);
  return onChange;
}

describe("generated sets, authored without the Assistant", () => {
  it("adds a range, checked as it is filled", () => {
    const onChange = mount();
    fireEvent.click(screen.getByRole("button", { name: /Add: Numbers from/ }));
    const recipe = screen.getByRole("group", { name: "Recipe" });
    expect(within(recipe).getByRole("status")).toHaveTextContent("set is a name"); // nothing named yet
    fireEvent.change(within(recipe).getByLabelText("Set name"), { target: { value: "hour" } });
    fireEvent.change(within(recipe).getByLabelText("To"), { target: { value: "23" } });
    fireEvent.change(within(recipe).getByLabelText("From"), { target: { value: "0" } });
    expect(within(recipe).getByRole("status")).toHaveTextContent("Makes hour: 0 to 23");
    fireEvent.click(within(recipe).getByRole("button", { name: "Add the recipe" }));
    expect(onChange).toHaveBeenCalledWith([{ kind: "range", set: "hour", from: 0, to: 23 }]);
  });

  it("adds a product of two sets, linked and in the same ward", () => {
    const onChange = mount();
    fireEvent.click(screen.getByRole("button", { name: /Add: Every combination/ }));
    const recipe = screen.getByRole("group", { name: "Recipe" });
    fireEvent.change(within(recipe).getByLabelText("Set name"), { target: { value: "assign" } });
    fireEvent.change(within(recipe).getByLabelText("Part 1"), { target: { value: "nurse" } });
    fireEvent.change(within(recipe).getByLabelText("Part 2"), { target: { value: "shift" } });
    fireEvent.change(within(recipe).getByLabelText("Only pairs linked by"), { target: { value: "can_work" } });
    fireEvent.change(within(recipe).getByLabelText("Same values"), { target: { value: "ward=ward" } });
    fireEvent.click(within(recipe).getByRole("button", { name: "Add the recipe" }));
    expect(onChange).toHaveBeenCalledWith([{ kind: "product", set: "assign", of: ["nurse", "shift"], linked: "can_work",
      same: [["ward", "ward"]] }]);
  });

  it("adds the positions of a layout with an aisle, and refuses a name already taken", () => {
    const onChange = mount();
    fireEvent.click(screen.getByRole("button", { name: /Add: Every position/ }));
    const recipe = screen.getByRole("group", { name: "Recipe" });
    fireEvent.change(within(recipe).getByLabelText("Areas (polygons)"), { target: { value: "area" } });
    fireEvent.change(within(recipe).getByLabelText("Item kinds"), { target: { value: "item_kind" } });
    fireEvent.change(within(recipe).getByLabelText("Aisle (cells)"), { target: { value: "1" } });
    fireEvent.change(within(recipe).getByLabelText("Positions set"), { target: { value: "area" } });
    expect(within(recipe).getByRole("status")).toHaveTextContent("generate_name_taken");
    expect(within(recipe).getByRole("button", { name: "Add the recipe" })).toBeDisabled();
    fireEvent.change(within(recipe).getByLabelText("Positions set"), { target: { value: "item" } });
    fireEvent.click(within(recipe).getByRole("button", { name: "Add the recipe" }));
    expect(onChange.mock.calls[0][0][0]).toMatchObject({ kind: "positions", areas: "area", kinds: "item_kind", aisle: 1,
      aisle_sides: "any", keeps_free: "keeps_free", items: "item", cells: "cell", occupies: "occupies" });
  });

  it("lists, edits and removes the recipes it has", () => {
    const onChange = mount([{ kind: "range", set: "hour", from: 0, to: 23 }]);
    expect(screen.getByText("hour: 0 to 23")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "47" } });
    fireEvent.click(screen.getByRole("button", { name: "Keep the changes" }));
    expect(onChange).toHaveBeenLastCalledWith([{ kind: "range", set: "hour", from: 0, to: 47 }]);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
