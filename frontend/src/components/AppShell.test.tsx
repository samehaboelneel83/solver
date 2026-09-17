import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "./AppShell";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders(initialEntries: string[] = ["/"]) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue([
      { schema: "iam", table: "organization", fields: [] },
      { schema: "domain", table: "entity", fields: [] },
    ]);
  });

  it("renders a nav group per schema with a link per table", async () => {
    renderWithProviders();

    expect(await screen.findByText("organization")).toBeInTheDocument();
    expect(screen.getByText("entity")).toBeInTheDocument();
    expect(screen.getByText("iam")).toBeInTheDocument();
    expect(screen.getByText("domain")).toBeInTheDocument();
  });

  it("renders a 'Skip to content' link as the first focusable element, targeting #main", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Skip to content");
    expect(links[0]).toHaveAttribute("href", "#main");
  });

  it("marks the nav link for the current route as active and leaves the others plain", async () => {
    renderWithProviders(["/iam/organization"]);
    const activeLink = await screen.findByRole("link", { name: "organization" });
    const otherLink = screen.getByRole("link", { name: "entity" });

    expect(activeLink).toHaveAttribute("aria-current", "page");
    expect(activeLink.className).not.toBe(otherLink.className);
    expect(otherLink).not.toHaveAttribute("aria-current");
  });

  it("renders <main> as a shrinkable flex child with id=main", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const main = document.getElementById("main");
    expect(main).not.toBeNull();
    expect(main?.className.split(/\s+/)).toContain("min-w-0");
  });
});
