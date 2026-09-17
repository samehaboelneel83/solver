import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { setToken } from "./api/client";

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "./api/client";

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

describe("RequireAuth", () => {
  beforeEach(() => {
    setToken(null);
  });

  it("redirects to /login with next=<current path> and no reason when there is no token", () => {
    render(
      <MemoryRouter initialEntries={["/finance/invoice?tab=details"]}>
        <LocationDisplay />
        <App />
      </MemoryRouter>
    );

    expect(screen.getByTestId("location").textContent).toBe(
      "/login?next=" + encodeURIComponent("/finance/invoice?tab=details")
    );
  });
});

describe("catch-all route", () => {
  beforeEach(() => {
    setToken("test-token");
    (apiFetch as any).mockResolvedValue([]);
  });

  it("renders the not-found page (inside the authenticated shell) for an unknown route", async () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/definitely/not/a/route/at/all"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to dashboard/i })).toHaveAttribute("href", "/");
  });
});
