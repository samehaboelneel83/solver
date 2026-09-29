import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
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
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/finance/invoice?tab=details"]}>
          <LocationDisplay />
          <App />
        </MemoryRouter>
      </QueryClientProvider>
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

describe("entity type routes (Task 11)", () => {
  beforeEach(() => {
    setToken("test-token");
    localStorage.removeItem("solver_domain_id");
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/v1/entity-types/5") {
        return Promise.resolve({ id: 5, domain_id: 7, name: "employee", role: "agent", attributes: [] });
      }
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });

  function renderAt(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("/entity-types renders the entity type list, not the not-found page", async () => {
    renderAt("/entity-types");
    expect(await screen.findByRole("heading", { level: 1, name: "Record types" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("/entity-types/:id renders the type editor, not the generic table page it would otherwise match", async () => {
    renderAt("/entity-types/5");
    expect(await screen.findByRole("heading", { level: 1, name: /employee/ })).toBeInTheDocument();
    expect(screen.queryByText(/unknown table/i)).not.toBeInTheDocument();
  });
});

describe("relationship type routes (Task 14f)", () => {
  beforeEach(() => {
    setToken("test-token");
    localStorage.removeItem("solver_domain_id");
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/v1/relationship-types/21") {
        return Promise.resolve({
          id: 21,
          domain_id: 7,
          name: "works_on",
          from_type_id: 5,
          to_type_id: 9,
          cardinality: "many_to_many",
          is_hierarchy: false,
          colour: null,
        });
      }
      if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: [], total: 0 });
      if (path.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 0 });
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });

  function renderAt(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("/relationship-types renders the list, not the not-found page", async () => {
    renderAt("/relationship-types");
    expect(await screen.findByRole("heading", { level: 1, name: "Relationship types" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("/relationship-types/:id renders the editor, not the generic table page it would otherwise match", async () => {
    renderAt("/relationship-types/21");
    expect(await screen.findByRole("heading", { level: 1, name: /works_on/ })).toBeInTheDocument();
    expect(screen.queryByText(/unknown table/i)).not.toBeInTheDocument();
  });

  /* `/relationships` returned "Page not found" -- the plural, the rows
   * themselves, had no screen at all, and the generic `:schemaName/:tableName`
   * pair below cannot reach it either, since it is one segment. */
  it("/relationships renders the relationships page, not the not-found page", async () => {
    renderAt("/relationships");
    expect(await screen.findByRole("heading", { level: 1, name: "Relationships" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("keeps /relationship-types and /relationships apart", async () => {
    renderAt("/relationships");
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(/^Relationships$/);
  });
});

describe("entity routes (Task 12)", () => {
  beforeEach(() => {
    setToken("test-token");
    localStorage.removeItem("solver_domain_id");
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/v1/entity-types/5") {
        return Promise.resolve({ id: 5, domain_id: 7, name: "employee", role: "agent", attributes: [] });
      }
      if (path === "/api/v1/entities/42") {
        return Promise.resolve({ id: 42, entity_type_id: 5, key: "ahmed", label: null, sort_order: 0, active: true, attrs: {} });
      }
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });

  function renderAt(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("/entities renders the entity list, not the generic table page for a table named 'entities'", async () => {
    renderAt("/entities");
    expect(await screen.findByRole("heading", { level: 1, name: "Records" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("/entities/new renders the new-entity form rather than matching the :id route", async () => {
    renderAt("/entities/new?type=5");
    expect(await screen.findByRole("heading", { level: 1, name: /new entity/i })).toBeInTheDocument();
  });

  it("/entities/:id renders the entity record", async () => {
    renderAt("/entities/42");
    expect(await screen.findByRole("heading", { level: 1, name: /ahmed/ })).toBeInTheDocument();
  });
});

describe("parameter and version routes (Task 13)", () => {
  beforeEach(() => {
    setToken("test-token");
    localStorage.removeItem("solver_domain_id");
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });

  function renderAt(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  it("/parameters renders the parameter list, not the generic table page", async () => {
    renderAt("/parameters");
    expect(await screen.findByRole("heading", { level: 1, name: "Parameters" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("/versions renders the model version list", async () => {
    renderAt("/versions");
    expect(await screen.findByRole("heading", { level: 1, name: "Model versions" })).toBeInTheDocument();
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });
});


it("clears cached account data when authentication changes", () => {
  const client = new QueryClient();
  client.setQueryData(["private-account-data"], { owner: "previous" });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter></QueryClientProvider>);
  act(() => setToken("new-account-session"));
  expect(client.getQueryData(["private-account-data"])).toBeUndefined();
});
