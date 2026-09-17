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

  it("emits the default criteria on mount", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    expect(onChange).toHaveBeenCalledWith({ selectedTypes: null, search: "", highlightIds: null });
  });

  it("clears highlightIds when selectedNodeId becomes null while highlighting is still on", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId="e1" onChange={onChange} />
    );

    fireEvent.click(screen.getByTestId("filter-highlight-toggle"));
    expect(onChange).toHaveBeenLastCalledWith({
      selectedTypes: null,
      search: "",
      highlightIds: expect.arrayContaining(["e1", "e2"]),
    });

    rerender(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    expect(onChange).toHaveBeenLastCalledWith({ selectedTypes: null, search: "", highlightIds: null });
  });

  it("recomputes highlightIds for the newly-selected node when the selection changes while highlighting is on", () => {
    const onChange = vi.fn();
    const moreEdges = [
      ...edges,
      { id: "r2", source: "e3", target: "e2", type: "works_for", label: "Works For", attributes: {} },
    ];
    const { rerender } = render(
      <FilterBar entityTypes={entityTypes} edges={moreEdges} selectedNodeId="e1" onChange={onChange} />
    );

    fireEvent.click(screen.getByTestId("filter-highlight-toggle"));

    rerender(<FilterBar entityTypes={entityTypes} edges={moreEdges} selectedNodeId="e3" onChange={onChange} />);

    expect(onChange).toHaveBeenLastCalledWith({
      selectedTypes: null,
      search: "",
      highlightIds: expect.arrayContaining(["e3", "e2"]),
    });
  });
});
