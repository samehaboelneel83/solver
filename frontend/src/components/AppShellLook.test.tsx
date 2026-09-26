import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppShell, { whereAmI } from "./AppShell";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

function Where() {
  return <p data-testid="path">{useLocation().pathname}</p>;
}

function renderAt(path = "/") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="*" element={<Where />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("the app's look (queue R22)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.dir = "ltr";
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "sameh", display_name: null, capabilities: ["domain.edit"] });
      if (path.startsWith("/api/v1/runs")) {
        return Promise.resolve({ items: [{ id: 41, scenario_id: 5, status: "optimal", queued_at: new Date().toISOString(), finished_at: new Date().toISOString() }], total: 1 });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });
  afterEach(() => {
    document.documentElement.classList.remove("dark");
    document.documentElement.dir = "ltr";
  });

  it("names where you are in the breadcrumb, group then page", () => {
    expect(whereAmI("/entity-types")).toEqual({
      group: "Data structure",
      page: "Record types",
      purpose: "Define what kinds of records exist in this domain.",
    });
    expect(whereAmI("/public/problem/12")).toEqual({
      group: "Problems",
      page: "Problems",
      purpose: "Decisions to optimize in this domain.",
    });
    expect(whereAmI("/")).toEqual({
      group: "Home",
      page: "Home",
      purpose: "Continue planning from recent work.",
    });
    renderAt("/runs");
    const crumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(crumb).toHaveTextContent("Runs");
  });

  it("switches to dark and back, and remembers it", () => {
    renderAt();
    fireEvent.click(screen.getByRole("button", { name: "Switch to the dark theme" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("solver_theme")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Switch to the light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("turns the page right to left, and back", () => {
    renderAt();
    fireEvent.click(screen.getByRole("button", { name: "Right to left" }));
    expect(document.documentElement.dir).toBe("rtl");
    expect(localStorage.getItem("solver_dir")).toBe("rtl");
    fireEvent.click(screen.getByRole("button", { name: "Left to right" }));
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("opens the command search with Ctrl+K and goes to the page typed", () => {
    renderAt();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const search = screen.getByRole("combobox", { name: "Go to a page" });
    fireEvent.change(search, { target: { value: "param" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["ParametersDomains"]);
    fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByTestId("path")).toHaveTextContent("/parameters");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("lists recent runs under the bell, and signs out from the account menu", async () => {
    renderAt();
    fireEvent.click(screen.getByRole("button", { name: "Recent runs" }));
    expect(await screen.findByText("Run 41")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("menuitem", { name: /Sign out of sameh/ })).toBeInTheDocument();
  });

  it("shrinks the desktop sidebar to its icons, names kept for screen readers", () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: true, media: query, onchange: null, addEventListener() {}, removeEventListener() {} })) as never;
    try {
      renderAt();
      fireEvent.click(screen.getByRole("button", { name: "Collapse the sidebar" }));
      expect(document.getElementById("sidebar-nav")).toHaveClass("w-16");
      expect(screen.getByRole("link", { name: "Parameters" })).toBeInTheDocument();
      expect(localStorage.getItem("solver_nav_collapsed")).toBe("1");
    } finally {
      window.matchMedia = original;
    }
  });
});
