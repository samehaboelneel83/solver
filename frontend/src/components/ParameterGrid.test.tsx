import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ParameterGrid from "./ParameterGrid";
import { ToastProvider } from "./ToastProvider";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

/*
 * The fixture is built so that a wrong implementation cannot pass by luck:
 *
 * - 2 rows x 3 columns, so swapping the axes changes the shape.
 * - Neither axis is in id order, nor in key order, so an implementation
 *   that re-sorted (or ignored) the API's order would be caught.
 * - The default is 4, and the stored values include 0 (distinct from the
 *   default) and 4 (equal to it, which `PATCH default_value` can leave
 *   behind), so "empty shows the default" cannot be confused with
 *   "everything is 0" or with "a cell equal to the default is empty".
 * - One entity has no label, so the `label ?? key` fallback is exercised.
 */

const PARAMETER = {
  id: 3,
  domain_id: 7,
  name: "demand",
  index_type_ids: [5, 9],
  default_value: 4,
  unit: "people",
};

// sort_order disagrees with both id order and alphabetical order.
const DAYS = {
  items: [
    { id: 44, entity_type_id: 5, key: "mon", label: "Monday", sort_order: 1, active: true, attrs: {} },
    { id: 42, entity_type_id: 5, key: "tue", label: null, sort_order: 2, active: true, attrs: {} },
  ],
  total: 2,
};

const SHIFTS = {
  items: [
    { id: 93, entity_type_id: 9, key: "morning", label: "Morning", sort_order: 1, active: true, attrs: {} },
    { id: 91, entity_type_id: 9, key: "evening", label: "Evening", sort_order: 2, active: true, attrs: {} },
    { id: 92, entity_type_id: 9, key: "night", label: "Night", sort_order: 3, active: true, attrs: {} },
  ],
  total: 3,
};

const VALUES = {
  index_types: [
    { id: 5, name: "day" },
    { id: 9, name: "shift" },
  ],
  cells: [
    { entity_ids: [44, 91], value: 7 }, // Monday x Evening
    { entity_ids: [42, 93], value: 0 }, // tue x Morning -- zero is not "empty"
    { entity_ids: [44, 92], value: 4 }, // Monday x Night -- equal to the default, still stored
  ],
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
    if (path.startsWith("/api/v1/parameters/3/values")) return Promise.resolve(VALUES);
    if (path.startsWith("/api/v1/entities?entity_type_id=5")) return Promise.resolve(DAYS);
    if (path.startsWith("/api/v1/entities?entity_type_id=9")) return Promise.resolve(SHIFTS);
    return Promise.reject(new Error(`unexpected ${init?.method ?? "GET"} ${path}`));
  });
}

function renderGrid(parameter: Record<string, unknown> = PARAMETER) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ParameterGrid parameter={parameter as never} />
      </ToastProvider>
    </QueryClientProvider>
  );
}

function puts(): { path: string; body: unknown }[] {
  return mockFetch.mock.calls
    .filter((call) => (call[1] as RequestInit | undefined)?.method === "PUT")
    .map((call) => ({ path: call[0] as string, body: JSON.parse((call[1] as RequestInit).body as string) }));
}

async function cell(name: string): Promise<HTMLInputElement> {
  return (await screen.findByLabelText(name)) as HTMLInputElement;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("ParameterGrid: the matrix itself", () => {
  it("puts the first index down the rows and the second across the columns, headed by entity labels", async () => {
    serve();
    renderGrid();

    const table = await screen.findByRole("table", { name: /demand/i });
    const headerCells = within(table).getAllByRole("columnheader").map((th) => th.textContent?.trim());
    // Three column headers for the second index, in the API's order, after
    // the corner cell naming the first index.
    expect(headerCells).toEqual(["day \\ shift", "Morning", "Evening", "Night"]);

    const rowHeaders = within(table).getAllByRole("rowheader").map((th) => th.textContent?.trim());
    // `tue` has no label, so its key is shown instead.
    expect(rowHeaders).toEqual(["Monday", "tue"]);
  });

  it("puts each stored value in its own cell, by coordinate rather than by position", async () => {
    serve();
    renderGrid();

    expect((await cell("demand[Monday, Evening]")).value).toBe("7");
    // Zero is a value, not an empty cell.
    expect((await cell("demand[tue, Morning]")).value).toBe("0");
    // A stored cell that happens to equal the default -- which `PATCH
    // default_value` leaves behind, since it never rewrites cells -- is
    // still a stored cell, and is shown as one rather than as empty.
    const redundant = await cell("demand[Monday, Night]");
    expect(redundant.value).toBe("4");
    expect(redundant).toHaveAttribute("data-stored", "true");
    expect(redundant).not.toHaveAttribute("placeholder");
    // ...and the transpose of a stored cell is empty, so the axes cannot be swapped.
    expect((await cell("demand[tue, Evening]")).value).toBe("");
    expect(screen.queryByLabelText("demand[Evening, Monday]")).not.toBeInTheDocument();
  });

  it("shows the default in an empty cell, visually distinguished from a stored value", async () => {
    serve();
    renderGrid();

    const empty = await cell("demand[Monday, Morning]");
    expect(empty.value).toBe("");
    expect(empty).toHaveAttribute("placeholder", "4");
    expect(empty).toHaveAttribute("data-stored", "false");

    const stored = await cell("demand[Monday, Evening]");
    expect(stored).toHaveAttribute("data-stored", "true");
    expect(stored).not.toHaveAttribute("placeholder");
    // The distinction is visible, not only in the accessibility tree.
    expect(empty.className).not.toEqual(stored.className);
  });

  it("says values are whole numbers and what the default is", async () => {
    serve();
    renderGrid();

    const note = await screen.findByTestId("grid-rules");
    expect(note.textContent).toMatch(/whole numbers/i);
    expect(note.textContent).toMatch(/\b4\b/);
    expect(note.textContent).toMatch(/people/);
  });

  it("scrolls the grid inside its own container", async () => {
    serve();
    renderGrid();

    const scroller = await screen.findByTestId("grid-scroll");
    expect(scroller.className).toMatch(/overflow-auto/);
    expect(scroller.className).toMatch(/max-h-/);
  });
});

describe("ParameterGrid: editing", () => {
  it("sends only the edited cells, as integers, in one PUT", async () => {
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].path).toBe("/api/v1/parameters/3/values");
    expect(puts()[0].body).toEqual({ cells: [{ entity_ids: [44, 93], value: 12 }] });
  });

  it("sends the default value for a cell cleared to empty, so the server deletes the row", async () => {
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Evening]"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ cells: [{ entity_ids: [44, 91], value: 4 }] });
  });

  it("sends a cell typed as the default too, rather than treating it as no change", async () => {
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Evening]"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ cells: [{ entity_ids: [44, 91], value: 4 }] });
  });

  it("shows what the server stored once a save succeeds, rather than what was typed", async () => {
    // The PUT is answered by a grid that does not contain the edit (the
    // server refused nothing -- it deleted the cell, or another writer got
    // there first): what is on screen afterwards has to be the server's
    // answer, not the draft.
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    await waitFor(() => expect(screen.getByLabelText("demand[Monday, Morning]")).toHaveValue(""));
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("cannot be saved when nothing was edited", async () => {
    serve();
    renderGrid();

    await screen.findByRole("table", { name: /demand/i });
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    expect(puts()).toHaveLength(0);
  });

  it("stops typing an unedited cell back to what it already held from sending anything", async () => {
    serve();
    renderGrid();

    const stored = await cell("demand[Monday, Evening]");
    fireEvent.change(stored, { target: { value: "8" } });
    fireEvent.change(stored, { target: { value: "7" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /save/i })).toBeDisabled());
    expect(puts()).toHaveLength(0);
  });
});

describe("ParameterGrid: integers only, refused before the request", () => {
  it.each([
    ["2.5", /whole number/i],
    ["abc", /whole number/i],
    ["5e3", /whole number/i],
    ["2147483648", /between/i],
  ])("refuses %s client-side and sends nothing", async (typed, message) => {
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: typed } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByTestId("form-errors")).toHaveTextContent(message);
    expect(puts()).toHaveLength(0);
  });

  it("names the offending cell, and marks that cell only", async () => {
    serve({ "PUT /api/v1/parameters/3/values": VALUES });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "2.5" } });
    fireEvent.change(await cell("demand[tue, Night]"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByTestId("form-errors")).toHaveTextContent("demand[Monday, Morning]");
    expect(await cell("demand[Monday, Morning]")).toHaveAttribute("aria-invalid", "true");
    expect(await cell("demand[tue, Night]")).not.toHaveAttribute("aria-invalid");
    expect(puts()).toHaveLength(0);
  });
});

describe("ParameterGrid: a rejected cell is shown on the cell that was rejected", () => {
  function indexError(index: number) {
    return new ApiError(
      422,
      JSON.stringify({
        detail: [
          {
            type: "value_error",
            loc: ["body", "cells", index, "entity_ids"],
            msg: "entity_ids must name 2 existing entities, one of each index type in this order: (day, shift)",
            kind: "parameter_index",
          },
        ],
      })
    );
  }

  it("maps the 422's cell index back to the cell the user edited", async () => {
    // Two edited cells, so an off-by-one mapping cannot land on the right one.
    serve({ "PUT /api/v1/parameters/3/values": indexError(1) });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "1" } });
    fireEvent.change(await cell("demand[tue, Night]"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    // The order the cells were sent in is what the index refers to.
    expect((puts()[0].body as { cells: { entity_ids: number[] }[] }).cells.map((c) => c.entity_ids)).toEqual([
      [44, 93],
      [42, 92],
    ]);
    await waitFor(() => expect(screen.getByLabelText("demand[tue, Night]")).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByLabelText("demand[Monday, Morning]")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByTestId("form-errors")).toHaveTextContent("demand[tue, Night]");
  });

  it("maps index 0 to the first cell sent, not to whichever cell is first on screen", async () => {
    serve({ "PUT /api/v1/parameters/3/values": indexError(0) });
    renderGrid();

    // Edited in reverse screen order; the request order is still row-major.
    fireEvent.change(await cell("demand[tue, Night]"), { target: { value: "2" } });
    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByLabelText("demand[Monday, Morning]")).toHaveAttribute("aria-invalid", "true")
    );
    expect(screen.getByLabelText("demand[tue, Night]")).not.toHaveAttribute("aria-invalid");
  });

  it("shows an error that names no cell as a general message", async () => {
    serve({
      "PUT /api/v1/parameters/3/values": new ApiError(409, JSON.stringify({ detail: "parameter is locked" })),
    });
    renderGrid();

    fireEvent.change(await cell("demand[Monday, Morning]"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText(/parameter is locked/)).toBeInTheDocument();
    expect(screen.getByLabelText("demand[Monday, Morning]")).not.toHaveAttribute("aria-invalid");
  });
});

describe("ParameterGrid: shapes other than two indexes", () => {
  const ONE = { ...PARAMETER, id: 3, index_type_ids: [5] };
  const ONE_VALUES = {
    index_types: [{ id: 5, name: "day" }],
    cells: [{ entity_ids: [42], value: 9 }],
    default_value: 4,
  };

  it("renders a one-index parameter as a single value column", async () => {
    serve({ "/api/v1/parameters/3/values": ONE_VALUES });
    renderGrid(ONE);

    const table = await screen.findByRole("table", { name: /demand/i });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent?.trim())).toEqual(["day", "Value"]);
    expect((await cell("demand[tue]")).value).toBe("9");
    expect((await cell("demand[Monday]")).value).toBe("");
  });

  const THREE = { ...PARAMETER, id: 3, index_type_ids: [5, 9, 5] };
  const THREE_VALUES = {
    index_types: [
      { id: 5, name: "day" },
      { id: 9, name: "shift" },
      { id: 5, name: "day" },
    ],
    cells: [
      { entity_ids: [44, 91, 42], value: 7 },
      { entity_ids: [42, 93, 44], value: 1 },
    ],
    default_value: 4,
  };

  it("falls back to a flat list of index/value rows for three or more indexes", async () => {
    serve({ "/api/v1/parameters/3/values": THREE_VALUES });
    renderGrid(THREE);

    const table = await screen.findByRole("table", { name: /demand/i });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent?.trim())).toEqual([
      "day",
      "shift",
      "day",
      "Value",
    ]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getAllByRole("cell").slice(0, 3).map((td) => td.textContent?.trim())).toEqual([
      "Monday",
      "Evening",
      "tue",
    ]);
    expect((await cell("demand[Monday, Evening, tue]")).value).toBe("7");
    expect(screen.getByTestId("flat-note").textContent).toMatch(/three/i);
  });

  it("edits a cell of a three-index parameter through the same PUT", async () => {
    serve({ "/api/v1/parameters/3/values": THREE_VALUES, "PUT /api/v1/parameters/3/values": THREE_VALUES });
    renderGrid(THREE);

    fireEvent.change(await cell("demand[tue, Morning, Monday]"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ cells: [{ entity_ids: [42, 93, 44], value: 5 }] });
  });
});

describe("ParameterGrid: states that are not a grid", () => {
  it("explains a deleted index type instead of rendering a broken grid", async () => {
    serve({
      "/api/v1/parameters/3/values": {
        ...VALUES,
        index_types: [
          { id: 5, name: "day" },
          { id: 9, name: null },
        ],
      },
    });
    renderGrid();

    expect(await screen.findByText(/no longer exists/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says so when an index type has no entities, rather than showing an empty table", async () => {
    serve({ "/api/v1/entities?entity_type_id=9": { items: [], total: 0 } });
    renderGrid();

    expect(await screen.findByText(/has no entities yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("warns when an axis has more entities than it loaded, instead of silently truncating", async () => {
    serve({ "/api/v1/entities?entity_type_id=9": { ...SHIFTS, total: 900 } });
    renderGrid();

    expect(await screen.findByText(/first 3 of 900/i)).toBeInTheDocument();
  });

  it("asks each axis for the API's largest page, so the warning is the only way a grid is short", async () => {
    serve();
    renderGrid();

    await screen.findByRole("table", { name: /demand/i });
    const entityCalls = mockFetch.mock.calls
      .map((call) => call[0] as string)
      .filter((path) => path.startsWith("/api/v1/entities"));
    expect(entityCalls).toHaveLength(2);
    for (const path of entityCalls) expect(path).toContain("limit=500");
  });
});
