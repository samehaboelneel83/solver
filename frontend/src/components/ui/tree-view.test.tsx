import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TreeItem } from "./tree-view";

describe("TreeItem", () => {
  it("shows nested children while open, and hides them when collapsed", () => {
    render(
      <TreeItem itemId="sum" name="Of" defaultOpen header={<span>sum</span>}>
        <p>inner term</p>
      </TreeItem>
    );

    expect(screen.getByText("inner term")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /collapse of/i }));
    expect(screen.queryByText("inner term")).not.toBeInTheDocument();
  });

  it("a leaf has no collapse control and still shows its body", () => {
    render(
      <TreeItem itemId="const" name="Value" leaf header={<span>a number</span>}>
        <p>the value field</p>
      </TreeItem>
    );

    expect(screen.queryByRole("button", { name: /collapse/i })).not.toBeInTheDocument();
    expect(screen.getByText("the value field")).toBeInTheDocument();
  });
});
