import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Entities from "./Entities";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { editorQueryClient } from "../test/me";

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
  const queryClient = editorQueryClient();
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
    // Task 14d: the page asks for these to offer `count(...)` in the
    // condition builder. Served rather than left to the reject below, so
    // the suite does not carry fifteen rejected promises that outlive the
    // tests that started them.
    if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: [], total: 0 });
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
    const chooser = (await screen.findByLabelText(/^Kind of record/)) as HTMLSelectElement;
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
    fireEvent.change(await screen.findByLabelText(/^Kind of record/), { target: { value: "9" } });
    await waitFor(() => expect(paths().some((p) => p.includes("entity_type_id=9"))).toBe(true));
    expect(screen.getByRole("link", { name: /new record/i })).toHaveAttribute("href", "/entities/new?type=9");
  });

  it("honours a type given in the query string, so a list can be linked to", async () => {
    serve();
    renderPage("/entities?type=9");
    await waitFor(() => expect(paths().some((p) => p.includes("entity_type_id=9"))).toBe(true));
    expect(((await screen.findByLabelText(/^Kind of record/)) as HTMLSelectElement).value).toBe("9");
  });

  it("offers the first kind of record in place when the domain has none", async () => {
    serve({
      "/api/v1/entity-types": { items: [], total: 0 },
      "/api/v1/me": { username: "modeller", capabilities: ["domain.edit"] },
    });
    renderPage();
    expect(await screen.findByText(/no kinds of record yet/)).toBeInTheDocument();
    expect(await screen.findByRole("form", { name: "New kind of record" })).toBeInTheDocument();
    expect(paths().some((p) => p.startsWith("/api/v1/entities"))).toBe(false);
  });

  it("makes a new kind of record, and a field on one, from the records page", async () => {
    serve({ "/api/v1/me": { username: "modeller", capabilities: ["domain.edit"] } });
    const writes: [string, unknown][] = [];
    const served = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
      if (options?.method === "POST") {
        writes.push([path, JSON.parse(options.body ?? "{}")]);
        return Promise.resolve(path.endsWith("/attributes") ? { id: 90 } : { id: 88, name: "shift", attributes: [] });
      }
      return served(path, options);
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /\+ Add a field to/ }));
    fireEvent.change(screen.getByPlaceholderText("hours per week"), { target: { value: "Hours per week" } });
    expect(screen.getByText("hours_per_week")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /which is/ }), { target: { value: "integer" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0][1]).toEqual({ name: "hours_per_week", data_type: "integer" });

    fireEvent.click(screen.getByRole("button", { name: "+ New kind of record" }));
    fireEvent.change(screen.getByPlaceholderText("employee"), { target: { value: "Shift" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]).toEqual(["/api/v1/entity-types", { domain_id: 7, name: "shift" }]);
  });
});

describe("Entities: a link field from the records page", () => {
  it("adds a field that links to a record of another kind", async () => {
    serve({ "/api/v1/me": { username: "modeller", capabilities: ["domain.edit"] } });
    const writes: [string, unknown][] = [];
    const served = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
      if (options?.method === "POST") {
        writes.push([path, JSON.parse(options.body ?? "{}")]);
        return Promise.resolve({ id: 91 });
      }
      return served(path, options);
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /\+ Add a field to/ }));
    fireEvent.change(screen.getByPlaceholderText("hours per week"), { target: { value: "usual shift" } });
    fireEvent.change(screen.getByRole("combobox", { name: /which is/ }), { target: { value: "reference" } });
    const add = screen.getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    const to = screen.getByRole("combobox", { name: /to a/ });
    await waitFor(() => expect(within(to).getByRole("option", { name: "shift" })).toBeInTheDocument());
    fireEvent.change(to, { target: { value: "9" } });
    fireEvent.click(add);
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0][1]).toEqual({ name: "usual_shift", data_type: "reference", target_type_id: 9 });
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

  it("switches the page of records to an editable grid and back", async () => {
    serve();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Edit as grid" }));
    expect(await screen.findByTestId("record-grid")).toBeInTheDocument();
    expect(screen.getByLabelText("zoe: key")).toHaveValue("zoe");
    fireEvent.click(screen.getByRole("button", { name: "Back to the list" }));
    expect(screen.queryByTestId("record-grid")).toBeNull();
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
    expect(await screen.findByText(/no \w+ records yet/i)).toBeInTheDocument();
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
    expect(await screen.findByRole("link", { name: /new record/i })).toHaveAttribute("href", "/entities/new?type=5");
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
