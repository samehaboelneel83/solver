import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Parameters from "./Parameters";
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
    { id: 5, domain_id: 7, name: "day", role: "time", attributes: [] },
    { id: 9, domain_id: 7, name: "shift", role: "time", attributes: [] },
  ],
  total: 2,
};

// Two parameters over the same pair of types in opposite index orders: a
// page that showed the index types in any order but the stored one would
// render these two identically.
const PARAMETERS = {
  items: [
    { id: 3, domain_id: 7, name: "demand", index_type_ids: [5, 9], default_value: 4, unit: "people" },
    { id: 4, domain_id: 7, name: "supply", index_type_ids: [9, 5], default_value: 0, unit: null },
  ],
  total: 2,
};

const DAYS = {
  items: [
    { id: 44, entity_type_id: 5, key: "mon", label: "Monday", sort_order: 1, active: true, attrs: {} },
    { id: 42, entity_type_id: 5, key: "tue", label: "Tuesday", sort_order: 2, active: true, attrs: {} },
  ],
  total: 2,
};

const SHIFTS = {
  items: [
    { id: 93, entity_type_id: 9, key: "morning", label: "Morning", sort_order: 1, active: true, attrs: {} },
    { id: 91, entity_type_id: 9, key: "evening", label: "Evening", sort_order: 2, active: true, attrs: {} },
  ],
  total: 2,
};

const VALUES = {
  index_types: [
    { id: 5, name: "day" },
    { id: 9, name: "shift" },
  ],
  cells: [{ entity_ids: [44, 91], value: 7 }],
  default_value: 4,
};

function serve(over: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    for (const [prefix, value] of Object.entries(over)) {
      const [method, target] = prefix.includes(" ") ? prefix.split(" ") : ["GET", prefix];
      if ((init?.method ?? "GET") === method && path.startsWith(target)) {
        return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
      }
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(TYPES);
    if (path.startsWith("/api/v1/parameters/3/values")) return Promise.resolve(VALUES);
    if (path.startsWith("/api/v1/parameters")) return Promise.resolve(PARAMETERS);
    if (path.startsWith("/api/v1/entities?entity_type_id=5")) return Promise.resolve(DAYS);
    if (path.startsWith("/api/v1/entities?entity_type_id=9")) return Promise.resolve(SHIFTS);
    return Promise.reject(new Error(`unexpected ${init?.method ?? "GET"} ${path}`));
  });
}

function calls(method: string): { path: string; body: unknown }[] {
  return mockFetch.mock.calls
    .filter((call) => ((call[1] as RequestInit | undefined)?.method ?? "GET") === method)
    .map((call) => {
      const body = (call[1] as RequestInit | undefined)?.body;
      return { path: call[0] as string, body: typeof body === "string" ? JSON.parse(body) : undefined };
    });
}

function ShowSearch() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderPage(entry = "/parameters") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
          <ShowSearch />
          <Routes>
            <Route path="/parameters" element={<Parameters />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
});

describe("Parameters: the list", () => {
  it("asks for a domain first, and requests nothing, when none is selected", async () => {
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    serve();
    renderPage();

    expect(await screen.findByText(/choose a domain/i)).toBeInTheDocument();
    expect(mockFetch.mock.calls).toHaveLength(0);
  });

  it("lists the domain's parameters with their index types in index order", async () => {
    serve();
    renderPage();

    const table = await screen.findByRole("table", { name: /parameters/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]).getAllByRole("cell").map((td) => td.textContent?.trim())).toEqual([
      "day, shift",
      "4",
      "people",
      "Delete",
    ]);
    // `supply` is indexed the other way round, and says so.
    expect(within(rows[1]).getAllByRole("cell").map((td) => td.textContent?.trim())).toEqual([
      "shift, day",
      "0",
      "—",
      "Delete",
    ]);
    expect(mockFetch.mock.calls.map((c) => c[0] as string)).toContain("/api/v1/parameters?domain_id=7&limit=500");
  });

  it("names an index type that no longer exists by its id rather than leaving the cell blank", async () => {
    serve({
      "/api/v1/parameters": {
        items: [{ id: 3, domain_id: 7, name: "demand", index_type_ids: [5, 77], default_value: 4, unit: null }],
        total: 1,
      },
    });
    renderPage();

    const table = await screen.findByRole("table", { name: /parameters/i });
    const row = within(table).getAllByRole("row")[1];
    // An array column carries no foreign key, so a deleted entity type
    // leaves its id behind: show the id, not an empty space.
    expect(within(row).getAllByRole("cell")[0].textContent?.trim()).toBe("day, #77");
  });

  it("says so, rather than showing an empty table, when the domain has no parameters", async () => {
    serve({ "/api/v1/parameters": { items: [], total: 0 } });
    renderPage();

    expect(await screen.findByText(/no parameters in this domain yet/i)).toBeInTheDocument();
  });

  it("sends the user to define an entity type first when the domain has none", async () => {
    serve({ "/api/v1/entity-types": { items: [], total: 0 }, "/api/v1/parameters": { items: [], total: 0 } });
    renderPage();

    expect(await screen.findByRole("link", { name: /define an entity type/i })).toHaveAttribute(
      "href",
      "/entity-types"
    );
    expect(screen.queryByRole("form", { name: /new parameter/i })).not.toBeInTheDocument();
  });
});

describe("Parameters: opening one", () => {
  it("shows the grid of the parameter named in the query string", async () => {
    serve();
    renderPage("/parameters?parameter=3");

    expect(await screen.findByLabelText("demand[Monday, Evening]")).toHaveValue("7");
  });

  it("opens a parameter from the list and records it in the query string", async () => {
    serve();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "demand" }));
    expect(await screen.findByLabelText("demand[Monday, Evening]")).toHaveValue("7");
    // Recorded in the URL, so the grid can be linked to and survives a reload.
    expect(screen.getByTestId("search").textContent).toBe("?parameter=3");
  });

  it("shows nothing but a prompt until a parameter is chosen", async () => {
    serve();
    renderPage();

    await screen.findByRole("table", { name: /parameters/i });
    expect(screen.getByText(/choose a parameter above/i)).toBeInTheDocument();
    expect(mockFetch.mock.calls.map((c) => c[0] as string).some((p) => p.includes("/values"))).toBe(false);
  });

  it("ignores a parameter id that is not in this domain's list", async () => {
    serve();
    renderPage("/parameters?parameter=999");

    await screen.findByRole("table", { name: /parameters/i });
    expect(screen.getByText(/choose a parameter above/i)).toBeInTheDocument();
    expect(mockFetch.mock.calls.map((c) => c[0] as string).some((p) => p.includes("/999/"))).toBe(false);
  });
});

describe("Parameters: creating one", () => {
  async function openForm() {
    serve({ "POST /api/v1/parameters": PARAMETERS.items[0] });
    renderPage();
    return await screen.findByRole("form", { name: /new parameter/i });
  }

  it("sends the index types in the order they were chosen", async () => {
    const form = await openForm();

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "cost" } });
    fireEvent.change(within(form).getByLabelText("Index 1"), { target: { value: "9" } });
    fireEvent.click(within(form).getByRole("button", { name: /add an index/i }));
    fireEvent.change(within(form).getByLabelText("Index 2"), { target: { value: "5" } });
    fireEvent.change(within(form).getByLabelText(/^Default value/), { target: { value: "3" } });
    fireEvent.change(within(form).getByLabelText(/^Unit/), { target: { value: "euros" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    expect(calls("POST")[0].body).toEqual({
      domain_id: 7,
      name: "cost",
      index_type_ids: [9, 5],
      default_value: 3,
      unit: "euros",
    });
  });

  it("refuses a decimal default before sending anything, and says why", async () => {
    const form = await openForm();

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "cost" } });
    fireEvent.change(within(form).getByLabelText(/^Default value/), { target: { value: "2.5" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    expect(await within(form).findByTestId("form-errors")).toHaveTextContent(/whole number/i);
    expect(calls("POST")).toHaveLength(0);
  });

  it("refuses a name the server's pattern would reject, before sending anything", async () => {
    const form = await openForm();

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "Cost Per Day" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    expect(await within(form).findByTestId("form-errors")).toHaveTextContent(/lowercase/i);
    expect(calls("POST")).toHaveLength(0);
  });

  it("omits an empty unit rather than sending an empty string", async () => {
    const form = await openForm();

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "cost" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    expect(calls("POST")[0].body).toEqual({
      domain_id: 7,
      name: "cost",
      index_type_ids: [5],
      default_value: 0,
      unit: null,
    });
  });

  it("opens the parameter it just created", async () => {
    const form = await openForm();

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "cost" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    await waitFor(() => expect(screen.getByTestId("search").textContent).toBe("?parameter=3"));
  });

  it("puts a duplicate-name 409 on the name field", async () => {
    serve({
      "POST /api/v1/parameters": new ApiError(
        409,
        JSON.stringify({ detail: "a record with the same domain_id_name already exists" })
      ),
    });
    renderPage();
    const form = await screen.findByRole("form", { name: /new parameter/i });

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "demand" } });
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    expect(await within(form).findByTestId("form-errors")).toHaveTextContent(/already has a parameter/i);
  });

  it("shows the server's explanation when the same index type is used twice", async () => {
    serve({
      "POST /api/v1/parameters": new ApiError(
        422,
        JSON.stringify({
          detail: [
            {
              loc: ["body", "index_type_ids"],
              msg: "index type 'day' appears more than once. This is a temporary restriction",
            },
          ],
        })
      ),
    });
    renderPage();
    const form = await screen.findByRole("form", { name: /new parameter/i });

    fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "distance" } });
    fireEvent.click(within(form).getByRole("button", { name: /add an index/i }));
    fireEvent.click(within(form).getByRole("button", { name: /create parameter/i }));

    expect(await within(form).findByTestId("form-errors")).toHaveTextContent(/appears more than once/i);
  });
});

describe("Parameters: changing a definition", () => {
  it("patches only the fields that changed, and explains what a new default does to stored cells", async () => {
    serve({ "PATCH /api/v1/parameters/3": { ...PARAMETERS.items[0], default_value: 6 } });
    renderPage("/parameters?parameter=3");

    const form = await screen.findByRole("form", { name: /parameter settings/i });
    expect(form.textContent).toMatch(/stored cells are not rewritten/i);
    fireEvent.change(within(form).getByLabelText(/^Default value/), { target: { value: "6" } });
    fireEvent.click(within(form).getByRole("button", { name: /save settings/i }));

    await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
    expect(calls("PATCH")[0].path).toBe("/api/v1/parameters/3");
    expect(calls("PATCH")[0].body).toEqual({ default_value: 6 });
  });

  it("refuses a decimal default here too, without sending anything", async () => {
    serve();
    renderPage("/parameters?parameter=3");

    const form = await screen.findByRole("form", { name: /parameter settings/i });
    fireEvent.change(within(form).getByLabelText(/^Default value/), { target: { value: "1.5" } });
    fireEvent.click(within(form).getByRole("button", { name: /save settings/i }));

    expect(await within(form).findByTestId("form-errors")).toHaveTextContent(/whole number/i);
    expect(calls("PATCH")).toHaveLength(0);
  });

  it("does not offer to re-index a parameter, and says why", async () => {
    serve();
    renderPage("/parameters?parameter=3");

    const form = await screen.findByRole("form", { name: /parameter settings/i });
    expect(form.textContent).toMatch(/index types cannot be changed/i);
    expect(within(form).queryByLabelText("Index 1")).not.toBeInTheDocument();
  });
});

describe("Parameters: deleting one", () => {
  const confirmSpy = vi.spyOn(window, "confirm");
  afterEach(() => confirmSpy.mockReset());

  it("asks first, and sends nothing when the user cancels", async () => {
    confirmSpy.mockReturnValue(false);
    serve();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete demand" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(1));
    expect(confirmSpy.mock.calls[0][0]).toMatch(/demand/);
    expect(calls("DELETE")).toHaveLength(0);
  });

  it("deletes the parameter the button belongs to once confirmed", async () => {
    confirmSpy.mockReturnValue(true);
    serve({ "DELETE /api/v1/parameters/4": undefined });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete supply" }));

    await waitFor(() => expect(calls("DELETE")).toHaveLength(1));
    expect(calls("DELETE")[0].path).toBe("/api/v1/parameters/4");
  });
});
