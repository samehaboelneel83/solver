import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Help from "./Help";

describe("Help", () => {
  it("shows getting-started steps and template link", () => {
    render(
      <MemoryRouter>
        <Help topic="getting-started" />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Getting started" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Template library" })).toHaveAttribute(
      "href",
      "/public/template"
    );
  });

  it("points API reference at local OpenAPI docs", () => {
    render(
      <MemoryRouter>
        <Help topic="api" />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: /Open API docs/ })).toHaveAttribute("href", "/docs");
  });
});
