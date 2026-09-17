import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FilterBar from "./FilterBar";

const entityTypes = [
  { id: "t1", code: "employee", name: "Employee", is_abstract: false },
  { id: "t2", code: "unit", name: "Unit", is_abstract: false },
];

const edges = [{ id: "r1", source: "e1", target: "e2", type: "works_for", label: "Works For", attributes: {} }];

describe("FilterBar", () => {
  it("emits selectedTypes=null when all types are checked (default)", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "ahmed" } });

    expect(onChange).toHaveBeenCalledWith({ selectedTypes: null, search: "ahmed", highlightIds: null });
  });

  it("emits the remaining selected type codes when one is unchecked", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("filter-type-unit"));

    expect(onChange).toHaveBeenCalledWith({ selectedTypes: ["employee"], search: "", highlightIds: null });
  });

  it("computes one-hop neighbor ids when highlighting is toggled on with a selected node", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId="e1" onChange={onChange} />);

    fireEvent.click(screen.getByTestId("filter-highlight-toggle"));

    expect(onChange).toHaveBeenCalledWith({
      selectedTypes: null,
      search: "",
      highlightIds: expect.arrayContaining(["e1", "e2"]),
    });
  });

  it("disables the highlight toggle when nothing is selected", () => {
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={vi.fn()} />);
    expect(screen.getByTestId("filter-highlight-toggle")).toBeDisabled();
  });
});
