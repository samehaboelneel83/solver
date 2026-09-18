import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const counts = [
  { schema: "domain", table: "entity", label_plural: "Entities", total: 12 },
  { schema: "iam", table: "organization", label_plural: "Organizations", total: 3 },
];

const recentProblems = {
  items: [{ id: "p1", code: "gap-fix", name: "Reduce staffing gaps", status: "DRAFT" }],
  total: 1,
};

function mockDefaultResponses() {
  (apiFetch as any).mockImplementation((path: string) => {
    if (path === "/api/health") {
      return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
    }
    if (path === "/api/meta/counts") {
      return Promise.resolve(counts);
    }
    if (path.startsWith("/api/problem/problem")) {
      return Promise.resolve(recentProblems);
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

describe("Dashboard", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    mockDefaultResponses();
  });

  it("renders the three entry points a new user can start from (A-1)", async () => {
    renderWithProviders();

    expect(await screen.findByRole("link", { name: "Domain model" })).toHaveAttribute("href", "/domain/entity");
    expect(screen.getByRole("link", { name: "Problems" })).toHaveAttribute("href", "/problem/problem");
    expect(screen.getByRole("link", { name: "Graph" })).toHaveAttribute("href", "/graph");
  });

  it("renders a Recent problems section from a mocked list call", async () => {
    renderWithProviders();

    const link = await screen.findByRole("link", { name: /reduce staffing gaps/i });
    expect(link).toHaveAttribute("href", "/problem/problem/p1");

    const problemCalls = (apiFetch as any).mock.calls.filter(([path]: [string]) => path.startsWith("/api/problem/problem"));
    expect(problemCalls.length).toBe(1);
  });

  it("renders each row count as a link to that table's list, from a single counts request (A-2)", async () => {
    renderWithProviders();

    const entityLink = await screen.findByRole("link", { name: /entities/i });
    expect(entityLink).toHaveAttribute("href", "/domain/entity");
    expect(screen.getByText("12")).toBeInTheDocument();

    const orgLink = screen.getByRole("link", { name: /organizations/i });
    expect(orgLink).toHaveAttribute("href", "/iam/organization");

    // A-2: one request for every table's count, not the old one-request-per-table
    // fan-out (34 calls on a freshly migrated database).
    const countsCalls = (apiFetch as any).mock.calls.filter(([path]: [string]) => path === "/api/meta/counts");
    expect(countsCalls.length).toBe(1);
  });

  it("renders service health as a single line, not two large infrastructure cards", async () => {
    renderWithProviders();

    const health = await screen.findByTestId("service-health");
    expect(health.textContent).toContain("Postgres");
    expect(health.textContent).toContain("ClickHouse");
    // Exactly one health status line -- not a pair of separate cards.
    expect(screen.getAllByTestId("service-health")).toHaveLength(1);
  });

  it("renders a named empty state, not a bare blank section, when there are no problems yet (A-5)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      if (path === "/api/meta/counts") return Promise.resolve(counts);
      if (path.startsWith("/api/problem/problem")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    renderWithProviders();

    expect(await screen.findByText("No problems yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New problem" })).toHaveAttribute("href", "/problem/problem/new");
  });

  it("still renders a sensible row-counts panel when every table is genuinely empty (A-5)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      if (path === "/api/meta/counts") {
        return Promise.resolve([{ schema: "domain", table: "entity", label_plural: "Entities", total: 0 }]);
      }
      if (path.startsWith("/api/problem/problem")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    renderWithProviders();

    const link = await screen.findByRole("link", { name: /entities/i });
    expect(link).toHaveAttribute("href", "/domain/entity");
    // A zero count is a legitimate, readable state -- not indistinguishable
    // from a failed fetch.
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
