import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ColourField from "./ColourField";
import { fallbackColour, labelForeground } from "../lib/colour";

function renderField(props: Partial<React.ComponentProps<typeof ColourField>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <ColourField
      value={null}
      onChange={onChange}
      fallbackKey="22"
      sampleText="employee"
      {...props}
    />
  );
  return { onChange, ...utils };
}

describe("ColourField", () => {
  it("shows the fallback colour, and says so, when nothing is chosen", () => {
    renderField();
    const preview = screen.getByTestId("colour-preview");
    // The preview is not decorative: it is the only place in the app where
    // the canvas's colour choice can actually be seen, since the canvas
    // itself is a bitmap.
    expect(preview).toHaveAttribute("data-fill", fallbackColour("22"));
    expect(screen.getByTestId("colour-swatch")).toHaveValue(fallbackColour("22"));
    expect(screen.getByText(/No colour chosen/i)).toBeInTheDocument();
  });

  it("shows the chosen colour when there is one", () => {
    renderField({ value: "#1f77b4" });
    expect(screen.getByTestId("colour-preview")).toHaveAttribute("data-fill", "#1f77b4");
    expect(screen.getByTestId("colour-hex")).toHaveValue("#1f77b4");
  });

  it("draws the sample in the label colour the canvas would use", () => {
    // White and near-black in the same test, because a single fill cannot
    // tell a real computation from a hardcoded answer.
    const white = renderField({ value: "#ffffff" });
    expect(screen.getByTestId("colour-preview")).toHaveAttribute(
      "data-foreground",
      labelForeground("#ffffff")
    );
    expect(screen.getByTestId("colour-preview")).toHaveStyle({ color: labelForeground("#ffffff") });
    white.unmount();

    renderField({ value: "#0b0b0b" });
    expect(screen.getByTestId("colour-preview")).toHaveAttribute(
      "data-foreground",
      labelForeground("#0b0b0b")
    );
    // ... and they are not the same answer, which is the point.
    expect(labelForeground("#ffffff")).not.toBe(labelForeground("#0b0b0b"));
  });

  it("accepts a typed hex in either case and reports it lower case", () => {
    const { onChange } = renderField();
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#AABBCC" } });
    expect(onChange).toHaveBeenCalledWith("#aabbcc");
  });

  it("does not report a half-typed or wrong value, and explains it", () => {
    const { onChange } = renderField({ value: "#1f77b4" });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#1f7" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/six-digit hex colour/i)).toBeInTheDocument();
    expect(screen.getByTestId("colour-hex")).toHaveAttribute("aria-invalid", "true");
  });

  it("clears to null when the box is emptied", () => {
    const { onChange } = renderField({ value: "#1f77b4" });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("has an explicit 'use automatic', because a colour input has no empty state", () => {
    const { onChange } = renderField({ value: "#1f77b4" });
    fireEvent.click(screen.getByTestId("colour-clear"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("disables 'use automatic' when there is already no colour", () => {
    renderField({ value: null });
    expect(screen.getByTestId("colour-clear")).toBeDisabled();
  });

  it("reports the swatch's value like any other choice", () => {
    const { onChange } = renderField();
    fireEvent.change(screen.getByTestId("colour-swatch"), { target: { value: "#2ca02c" } });
    expect(onChange).toHaveBeenCalledWith("#2ca02c");
  });

  it("re-seeds when the stored value changes underneath it", () => {
    const { rerender } = render(
      <ColourField value={null} onChange={vi.fn()} fallbackKey="22" sampleText="employee" />
    );
    expect(screen.getByTestId("colour-hex")).toHaveValue("");
    rerender(
      <ColourField value="#ff8800" onChange={vi.fn()} fallbackKey="22" sampleText="employee" />
    );
    expect(screen.getByTestId("colour-hex")).toHaveValue("#ff8800");
  });

  it("labels both controls", () => {
    renderField({ label: "Colour" });
    expect(screen.getByLabelText("Colour")).toBe(screen.getByTestId("colour-hex"));
    expect(screen.getByLabelText("Colour swatch")).toBe(screen.getByTestId("colour-swatch"));
  });
});
