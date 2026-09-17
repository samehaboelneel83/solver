import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FilterBar, { DEFAULT_FILTER_STATE, deriveFilterCriteria } from "./FilterBar";
import type { FilterState } from "./FilterBar";

const entityTypes = [
  { id: "t1", code: "employee", name: "Employee", is_abstract: false },
  { id: "t2", code: "unit", name: "Unit", is_abstract: false },
];

const edges = [{ id: "r1", source: "e1", target: "e2", type: "works_for", label: "Works For", attributes: {} }];

describe("FilterBar", () => {
  it("renders a 'Types: n of m' button that opens a panel with a search box and name (code) checkboxes plus All/None", () => {
    render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId={null}
        value={DEFAULT_FILTER_STATE}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByTestId("filter-types-toggle")).toHaveTextContent("Types: 2 of 2");
    expect(screen.queryByTestId("filter-types-panel")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("filter-types-toggle"));

    expect(screen.getByTestId("filter-types-panel")).toBeInTheDocument();
    expect(screen.getByTestId("filter-type-search")).toBeInTheDocument();
    expect(screen.getByTestId("filter-types-all")).toBeInTheDocument();
    expect(screen.getByTestId("filter-types-none")).toBeInTheDocument();
    expect(screen.getByText("Employee (employee)")).toBeInTheDocument();
    expect(screen.getByText("Unit (unit)")).toBeInTheDocument();
  });

  it("calls onChange with the updated selectedTypes when a type checkbox is toggled", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId={null}
        value={DEFAULT_FILTER_STATE}
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByTestId("filter-types-toggle"));
    fireEvent.click(screen.getByTestId("filter-type-unit"));

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTER_STATE, selectedTypes: ["employee"] });
  });

  it("None clears selectedTypes to an empty array, All resets it to null", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId={null}
        value={DEFAULT_FILTER_STATE}
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByTestId("filter-types-toggle"));
    fireEvent.click(screen.getByTestId("filter-types-none"));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTER_STATE, selectedTypes: [] });

    const narrowed: FilterState = { ...DEFAULT_FILTER_STATE, selectedTypes: [] };
    rerender(
      <FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} value={narrowed} onChange={onChange} />
    );
    fireEvent.click(screen.getByTestId("filter-types-all"));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTER_STATE, selectedTypes: null });
  });

  it("updates search via onChange as the value prop, not internal state", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId={null}
        value={DEFAULT_FILTER_STATE}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "ahmed" } });

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTER_STATE, search: "ahmed" });
  });

  it("disables the highlight toggle when nothing is selected", () => {
    render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId={null}
        value={DEFAULT_FILTER_STATE}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("filter-highlight-toggle")).toBeDisabled();
  });

  it("toggles highlighting via onChange when a node is selected", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        entityTypes={entityTypes}
        edges={edges}
        selectedNodeId="e1"
        value={DEFAULT_FILTER_STATE}
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByTestId("filter-highlight-toggle"));

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTER_STATE, highlighting: true });
  });
});

describe("deriveFilterCriteria", () => {
  it("returns one-hop neighbor ids when highlighting is on and a node is selected", () => {
    const state: FilterState = { selectedTypes: null, search: "", highlighting: true };
    const result = deriveFilterCriteria(state, "e1", edges);

    expect(result.highlightIds).toEqual(expect.arrayContaining(["e1", "e2"]));
    expect(result.highlightIds).toHaveLength(2);
  });

  it("returns highlightIds: null when selectedNodeId is null, even if highlighting is on", () => {
    const state: FilterState = { selectedTypes: null, search: "", highlighting: true };
    const result = deriveFilterCriteria(state, null, edges);

    expect(result.highlightIds).toBeNull();
  });

  it("returns highlightIds: null when highlighting is off, even with a selected node", () => {
    const state: FilterState = { selectedTypes: null, search: "", highlighting: false };
    const result = deriveFilterCriteria(state, "e1", edges);

    expect(result.highlightIds).toBeNull();
  });

  it("passes selectedTypes and search through unchanged", () => {
    const state: FilterState = { selectedTypes: ["employee"], search: "ahmed", highlighting: false };
    const result = deriveFilterCriteria(state, null, edges);

    expect(result.selectedTypes).toEqual(["employee"]);
    expect(result.search).toBe("ahmed");
  });
});
