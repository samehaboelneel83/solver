import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Entities from "./Entities";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const TYPES = {
  items: [
    {
      id: 5,
      domain_id: 7,
      name: "employee",
      role: "agent",
      attributes: [
        { id: 11, entity_type_id: 5, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
        { id: 12, entity_type_id: 5, name: "on_call", data_type: "boolean", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 9, domain_id: 7, name: "shift", role: "time", attributes: [] },
  ],
  total: 2,
};

// `sort_order` disagrees with alphabetical order, so a page that re-sorted
// the API's answer would be caught.
const ENTITIES = {
  items: [
    { id: 42, entity_type_id: 5, key: "zoe", label: "Zoe", sort_order: 1, active: true, attrs: { grade: 0, on_call: false } },
    { id: 43, entity_type_id: 5, key: "ahmed", label: null, sort_order: 2, active: false, attrs: {} },
  ],
  total: 2,
};

function paths(): string[] {
  return mockFetch.mock.calls.map((call) => call[0] as string);
}

function renderPage(entry = "/entities") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/entities" element={<Entities />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function serve(over: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string) => {
    for (const [prefix, value] of Object.entries(over)) {
      if (path.startsWith(prefix)) {
        return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
      }
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(TYPES);
    if (path.startsWith("/api/v1/entities")) return Promise.resolve(ENTITIES);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
});

describe("Entities: choosing what to show", () => {
  it("asks for a domain first, and requests nothing, when none is selected", async () => {
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    serve();
    renderPage();
    expect(await screen.findByText(/choose a domain/i)).toBeInTheDocument();
    expect(paths()).toHaveLength(0);
  });

  it("offers the domain's entity types, because entities have no domain filter of their own", async () => {
    serve();
    renderPage();
    const chooser = (await screen.findByLabelText(/^Entity type/)) as HTMLSelectElement;
    expect(within(chooser).getAllByRole("option").map((o) => (o as HTMLOptionElement).textContent)).toEqual([
      "employee",
      "shift",
    ]);
    expect(paths().some((p) => p.startsWith("/api/v1/entity-types?domain_id=7"))).toBe(true);
  });

  it("lists the first type's entities until another is chosen", async () => {
    serve();
    renderPage();
    await screen.findByRole("link", { name: "zoe" });
    expect(paths().some((p) => p.includes("entity_type_id=5"))).toBe(true);
    expect(paths().some((p) => p.includes("entity_type_id=9"))).toBe(false);
  });

  it("switches list and deep link when another type is chosen", async () => {
    serve();
    renderPage();
    fireEvent.change(await screen.findByLabelText(/^Entity type/), { target: { value: "9" } });
    await waitFor(() => expect(paths().some((p) => p.includes("entity_type_id=9"))).toBe(true));
    expect(screen.getByRole("link", { name: /new entity/i })).toHaveAttribute("href", "/entities/new?type=9");
  });

  it("honours a type given in the query string, so a list can be linked to", async () => {
    serve();
    renderPage("/entities?type=9");
    await waitFor(() => expect(paths().some((p) => p.includes("entity_type_id=9"))).toBe(true));
    expect(((await screen.findByLabelText(/^Entity type/)) as HTMLSelectElement).value).toBe("9");
  });

  it("points at the entity types page when the domain has none", async () => {
    serve({ "/api/v1/entity-types": { items: [], total: 0 } });
    renderPage();
    expect(await screen.findByRole("link", { name: /entity type/i })).toHaveAttribute("href", "/entity-types");
    expect(paths().some((p) => p.startsWith("/api/v1/entities"))).toBe(false);
  });
});

describe("Entities: the list", () => {
  it("shows each entity's key, label, sort order and active flag in the API's order", async () => {
    serve();
    renderPage();
    const rows = within(await screen.findByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").length > 0)).toEqual([true, true]);
    expect(rows[0].textContent).toContain("zoe");
    expect(rows[1].textContent).toContain("ahmed");
  });

  it("gives every entity a link to its own record", async () => {
    serve();
    renderPage();
    expect(await screen.findByRole("link", { name: "zoe" })).toHaveAttribute("href", "/entities/42");
    expect(screen.getByRole("link", { name: "ahmed" })).toHaveAttribute("href", "/entities/43");
  });

  it("gives the type's attributes a column each and renders a false and a zero rather than blanks", async () => {
    serve();
    renderPage();
    const table = await screen.findByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent?.trim());
    expect(headers).toContain("grade");
    expect(headers).toContain("on_call");
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getByText("0")).toBeInTheDocument();
    expect(within(row).getByText("No")).toBeInTheDocument();
  });

  it("shows an em dash where an entity has no value for an attribute", async () => {
    serve();
    renderPage();
    const rows = within(await screen.findByRole("table")).getAllByRole("row");
    // `ahmed` holds neither attribute.
    expect(within(rows[2]).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("says the type has no entities yet rather than showing an empty table", async () => {
    serve({ "/api/v1/entities": { items: [], total: 0 } });
    renderPage();
    expect(await screen.findByText(/no entities/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("searches by key or label through the server, not in the browser", async () => {
    serve();
    renderPage();
    await screen.findByRole("link", { name: "zoe" });
    fireEvent.change(screen.getByLabelText(/^Search/), { target: { value: "ahm" } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));
    await waitFor(() => expect(paths().some((p) => p.includes("q=ahm"))).toBe(true));
  });

  it("offers a link to create an entity of the chosen type", async () => {
    serve();
    renderPage();
    expect(await screen.findByRole("link", { name: /new entity/i })).toHaveAttribute("href", "/entities/new?type=5");
  });

  it("reports a failed list with a retry", async () => {
    serve({ "/api/v1/entities": new ApiError(500, JSON.stringify({ detail: "boom" })) });
    renderPage();
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("pages through more entities than one page holds", async () => {
    serve({ "/api/v1/entities": { items: ENTITIES.items, total: 120 } });
    renderPage();
    const next = await screen.findByRole("button", { name: /next/i });
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    fireEvent.click(next);
    await waitFor(() => expect(paths().some((p) => p.includes("offset=50"))).toBe(true));
  });
});
