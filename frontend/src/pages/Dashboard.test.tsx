import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
      <Dashboard />
    </QueryClientProvider>
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") {
        return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      }
      if (path === "/api/meta/schema") {
        return Promise.resolve([{ schema: "iam", table: "organization", fields: [] }]);
      }
      return Promise.resolve({ items: [{ id: "1" }], total: 1 });
    });
  });

  it("renders health status for both databases", async () => {
    renderWithProviders();
    const okValues = await screen.findAllByText("ok");
    expect(okValues.length).toBe(2);
  });

  it("renders a row count per table", async () => {
    renderWithProviders();
    expect(await screen.findByText("iam.organization")).toBeInTheDocument();
    expect(await screen.findByText("1")).toBeInTheDocument();
  });
});
