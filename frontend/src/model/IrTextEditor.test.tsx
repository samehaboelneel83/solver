import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IrTextEditor } from "./IrTextEditor";

const IR = { version: 2, sets: ["item"], parameters: {}, variables: { x: { index: ["item"], domain: "binary" } }, constraints: [] };

describe("the exact IR, edited as text", () => {
  it("applies an edit the contract accepts, including keys no form draws", () => {
    const onApply = vi.fn();
    render(<IrTextEditor ir={IR} canEdit onApply={onApply} />);
    const box = screen.getByLabelText("Exact IR (JSON)");
    const next = { ...IR, sets: ["area", "kind"], variables: { x: { index: ["hour"], domain: "binary" } },
      generate: [{ kind: "range", set: "hour", from: 0, to: 23 }] };
    fireEvent.change(box, { target: { value: JSON.stringify(next) } });
    expect(screen.getByRole("status")).toHaveTextContent("The contract accepts this model");
    fireEvent.click(screen.getByRole("button", { name: "Apply to the draft" }));
    expect(onApply).toHaveBeenCalledWith(next);
  });

  it("says where the JSON breaks, and what the contract refuses, as it is typed", () => {
    render(<IrTextEditor ir={IR} canEdit onApply={() => {}} />);
    const box = screen.getByLabelText("Exact IR (JSON)");
    fireEvent.change(box, { target: { value: '{"version": 2,\n "sets": [' } });
    expect(screen.getByRole("status")).toHaveTextContent("Not valid JSON");
    expect(screen.getByRole("button", { name: "Apply to the draft" })).toBeDisabled();
    fireEvent.change(box, { target: { value: JSON.stringify({ ...IR, generate: [{ kind: "grid" }] }) } });
    expect(screen.getByRole("status")).toHaveTextContent("generate_malformed at generate / 0 / kind");
    fireEvent.click(screen.getByRole("button", { name: "Discard edits" }));
    expect((box as HTMLTextAreaElement).value).toBe(JSON.stringify(IR, null, 2));
  });

  it("is read-only for an account that may not change the model", () => {
    render(<IrTextEditor ir={IR} canEdit={false} onApply={() => {}} />);
    expect(screen.getByLabelText("Exact IR (JSON)")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Apply to the draft" })).not.toBeInTheDocument();
  });
});
