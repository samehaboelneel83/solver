import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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
    localStorage.clear();
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

  it("lists the plural human label (e.g. 'Entity types') instead of the raw table name when the backend sends one (B-1)", async () => {
    (apiFetch as any).mockResolvedValue([
      { schema: "domain", table: "entity_type", label: "Entity type", label_plural: "Entity types", fields: [] },
    ]);
    renderWithProviders();

    expect(await screen.findByText("Entity types")).toBeInTheDocument();
    expect(screen.queryByText("entity_type")).not.toBeInTheDocument();
  });

  describe("collapsible groups (A-4)", () => {
    it("hides a group's tables when its heading is clicked, and shows them again on a second click", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const heading = screen.getByRole("button", { name: /iam/i });
      expect(screen.getByRole("link", { name: "organization" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
      // The other group is untouched.
      expect(screen.getByRole("link", { name: "entity" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(screen.getByRole("link", { name: "organization" })).toBeInTheDocument();
    });

    it("persists a collapsed group's state in localStorage and restores it on the next mount", async () => {
      const { unmount } = renderWithProviders();
      await screen.findByText("organization");

      fireEvent.click(screen.getByRole("button", { name: /iam/i }));
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();

      const stored = JSON.parse(localStorage.getItem("solver_nav_open_groups") ?? "{}");
      expect(stored.iam).toBe(false);

      unmount();

      renderWithProviders();
      await screen.findByText("entity");
      // Restored collapsed -- the table link stays hidden without clicking again.
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
    });
  });

  it("narrows the visible tables via the filter box", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    fireEvent.change(screen.getByPlaceholderText("Filter tables…"), { target: { value: "entity" } });

    expect(screen.getByRole("link", { name: "entity" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
  });

  it("scrolls the table nav region independently of the rest of the sidebar", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const nav = screen.getByRole("navigation", { name: "Tables" });
    expect(nav.className).toContain("overflow-y-auto");
  });

  describe("drawer below the lg breakpoint (G-2/G-5)", () => {
    it("always renders a menu toggle button, hidden above the drawer breakpoint via a responsive class", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toBeInTheDocument();
      expect(toggle.className).toContain("lg:hidden");
    });

    it("opens the sidebar via the menu button and closes it again on Escape", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.keyDown(document, { key: "Escape" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    });

    it("closes the drawer on route change", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.click(screen.getByRole("link", { name: "entity" }));
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    });
  });
});
