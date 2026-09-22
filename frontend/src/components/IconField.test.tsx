import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import IconField from "./IconField";

function renderField(props: Partial<React.ComponentProps<typeof IconField>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <IconField value={null} onChange={onChange} typeName="bus_stop" colour="#1f77b4" {...props} />
  );
  return { onChange, ...utils };
}

function file(name: string, type: string, content: BlobPart) {
  return new File([content], name, { type });
}

describe("IconField", () => {
  it("previews the default chosen from the name, and says where it came from", () => {
    renderField();
    expect(screen.getByTestId("icon-preview")).toHaveAttribute("data-icon", "bus_stop");
    expect(screen.getByText(/Default — Bus stop, chosen from this type's name/)).toBeInTheDocument();
    expect(screen.getByTestId("icon-default")).toBeDisabled();
  });

  it("falls back to the role, and says so", () => {
    renderField({ typeName: "widget", role: "agent" });
    expect(screen.getByTestId("icon-preview")).toHaveAttribute("data-icon", "person");
    expect(screen.getByText(/chosen from this type's role/)).toBeInTheDocument();
  });

  it("picks a gallery icon and closes the gallery", () => {
    const { onChange } = renderField();
    const toggle = screen.getByTestId("icon-gallery-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Hotel" }));
    expect(onChange).toHaveBeenCalledWith("hotel");
    expect(screen.queryByTestId("icon-gallery")).not.toBeInTheDocument();
  });

  it("marks the chosen icon as pressed", () => {
    renderField({ value: "hotel" });
    fireEvent.click(screen.getByTestId("icon-gallery-toggle"));
    expect(screen.getByRole("button", { name: "Hotel" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "City" })).toHaveAttribute("aria-pressed", "false");
  });

  it("goes back to the default", () => {
    const { onChange } = renderField({ value: "hotel" });
    fireEvent.click(screen.getByTestId("icon-default"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("uploads a PNG as a data URI", async () => {
    const { onChange } = renderField();
    fireEvent.change(screen.getByTestId("icon-file"), {
      target: { files: [file("a.png", "image/png", new Uint8Array([137, 80, 78, 71]))] },
    });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(onChange.mock.calls[0][0]).toMatch(/^data:image\/png;base64,/);
  });

  it("refuses an SVG with script before sending it", async () => {
    const { onChange } = renderField();
    fireEvent.change(screen.getByTestId("icon-file"), {
      target: { files: [file("a.svg", "image/svg+xml", "<svg><script>alert(1)</script></svg>")] },
    });
    expect(await screen.findByText(/This SVG contains a <script> element/)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("refuses the wrong kind of file", async () => {
    renderField();
    fireEvent.change(screen.getByTestId("icon-file"), {
      target: { files: [file("a.gif", "image/gif", "GIF89a")] },
    });
    expect(await screen.findByText(/Choose a PNG, SVG or WebP image/)).toBeInTheDocument();
  });

  it("shows the form's error for the field", () => {
    renderField({ error: "the uploaded image is 300 KB; the limit is 200 KB" });
    expect(screen.getByText(/300 KB/)).toBeInTheDocument();
  });

  it("disables every control when the user may not edit", () => {
    renderField({ disabled: true, value: "hotel" });
    for (const id of ["icon-gallery-toggle", "icon-upload", "icon-default"]) {
      expect(screen.getByTestId(id)).toBeDisabled();
    }
  });
});
