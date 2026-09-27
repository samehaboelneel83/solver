import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

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

// v1's `problem` is a public-schema table with `name`, `owner` and
// `created_at` -- no `code`, and no `status` (both were v0 columns).
const recentProblems = {
  items: [{ id: 31, domain_id: 7, name: "Reduce staffing gaps", owner: "ops", created_at: "2026-09-19T09:00:00Z" }],
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
    if (path.startsWith("/api/problem/")) {
      return Promise.resolve(recentProblems);
    }
    if (path.startsWith("/api/v1/me")) {
      return Promise.resolve({
        username: "admin",
        display_name: "Administrator",
        capabilities: ["domain.edit", "model.publish", "run.submit"],
      });
    }
    if (path.startsWith("/api/template")) {
      return Promise.resolve({ items: [], total: 0 });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

describe("Dashboard", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    mockDefaultResponses();
  });

  it("renders the three entry points a planner can continue from (OAAS N07)", async () => {
    renderWithProviders();

    expect(await screen.findByRole("heading", { level: 1, name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Domains" })).toHaveAttribute("href", "/public/domain");
    expect(screen.getByRole("link", { name: "Problems" })).toHaveAttribute("href", "/public/problem");
    expect(screen.getByRole("link", { name: "Runs & results" })).toHaveAttribute("href", "/runs");
  });

  it("renders a Recent problems section from a mocked list call", async () => {
    renderWithProviders();

    const link = await screen.findByRole("link", { name: /reduce staffing gaps/i });
    expect(link).toHaveAttribute("href", "/domains/7/problems/31/overview");

    // The v1 route (Ruling 27): `problem` lives in `public`, so the generic
    // path collapses to `/api/problem/`. The v0 `/api/problem/problem/` the
    // dashboard used to ask for was redirected to a portless host and failed
    // in the browser (Task 10's carry-forward).
    const problemCalls = (apiFetch as any).mock.calls.filter(([path]: [string]) => path.startsWith("/api/problem/"));
    expect(problemCalls.length).toBe(1);
    expect(problemCalls[0][0]).not.toContain("/api/problem/problem");
    // "Recent": newest first, which is what makes the panel worth reading.
    expect(problemCalls[0][0]).toContain("order_by=created_at");
    expect(problemCalls[0][0]).toContain("order=desc");
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
      if (path.startsWith("/api/problem/")) return Promise.resolve({ items: [], total: 0 });
      if (path.startsWith("/api/v1/me")) {
        return Promise.resolve({ username: "admin", capabilities: ["model.publish"] });
      }
      if (path.startsWith("/api/template")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    renderWithProviders();

    expect(await screen.findByText("No problems yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New problem" })).toHaveAttribute("href", "/public/problem/new");
  });

  it("scopes recent problems to the selected domain", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    renderWithProviders();

    await screen.findByRole("link", { name: /reduce staffing gaps/i });
    const problemCall = (apiFetch as any).mock.calls.find(([path]: [string]) => path.startsWith("/api/problem/"));
    expect(problemCall[0]).toContain("f_domain_id=7");
  });

  it("asks for every domain's problems when no domain is selected", async () => {
    renderWithProviders();

    await screen.findByRole("link", { name: /reduce staffing gaps/i });
    const problemCall = (apiFetch as any).mock.calls.find(([path]: [string]) => path.startsWith("/api/problem/"));
    expect(problemCall[0]).not.toContain("f_domain_id");
  });

    it("offers a template when no domain is selected yet", async () => {
      (apiFetch as any).mockImplementation((path: string) => {
        if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
        if (path === "/api/meta/counts") return Promise.resolve(counts);
        if (path.startsWith("/api/problem/")) return Promise.resolve({ items: [], total: 0 });
        if (path.startsWith("/api/v1/me")) {
          return Promise.resolve({ username: "admin", capabilities: ["model.publish"] });
        }
        if (path.startsWith("/api/template")) {
          return Promise.resolve({
            items: [{ id: 1, name: "weekly_rota", ir_version: "1", domain_seed: {}, default_ir: {} }],
            total: 1,
          });
        }
        return Promise.reject(new Error(`unexpected path ${path}`));
      });
      renderWithProviders();

      expect(await screen.findByRole("button", { name: /start from weekly_rota/i })).toBeInTheDocument();
    });

    it("opens an existing weekly rota rather than applying the template twice", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      if (path === "/api/meta/counts") return Promise.resolve(counts);
      if (path.startsWith("/api/problem/")) {
        return Promise.resolve({
          items: [{ id: 31, domain_id: 7, name: "weekly_rota", template_id: 1, owner: "ops", created_at: "2026-09-19T09:00:00Z" }],
          total: 1,
        });
      }
      if (path.startsWith("/api/v1/me")) {
        return Promise.resolve({ username: "admin", capabilities: ["model.publish"] });
      }
      if (path.startsWith("/api/template")) {
        return Promise.resolve({
          items: [{ id: 1, name: "weekly_rota", ir_version: "1", domain_seed: {}, default_ir: {} }],
          total: 1,
        });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    renderWithProviders();

    expect(await screen.findByRole("button", { name: /open weekly_rota/i })).toBeInTheDocument();
  });

  it("still renders a sensible row-counts panel when every table is genuinely empty (A-5)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      if (path === "/api/meta/counts") {
        return Promise.resolve([{ schema: "domain", table: "entity", label_plural: "Entities", total: 0 }]);
      }
      if (path.startsWith("/api/problem/")) return Promise.resolve({ items: [], total: 0 });
      if (path.startsWith("/api/v1/me")) {
        return Promise.resolve({ username: "admin", capabilities: ["model.publish"] });
      }
      if (path.startsWith("/api/template")) return Promise.resolve({ items: [], total: 0 });
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
