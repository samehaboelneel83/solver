import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RecordGrid, { pastedCells } from "./RecordGrid";
import { ToastProvider } from "./ToastProvider";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const attr = (id: number, name: string, data_type: string, extra = {}) => ({
  id, entity_type_id: 5, name, data_type, required: false, unit: null, enum_values: null, default_value: null, ...extra,
});

const TYPE = {
  id: 5, domain_id: 7, name: "truck", role: "resource",
  attributes: [attr(1, "capacity", "integer", { unit: "t" }), attr(2, "fuel", "enum", { enum_values: ["diesel", "electric"] }),
    attr(3, "parked", "geometry")],
};

const truck = (id: number, key: string, attrs: object) => ({
  id, entity_type_id: 5, key, label: null, sort_order: 0, active: true, attrs, updated_at: `t${id}`,
});

const RECORDS = [truck(1, "T1", { capacity: 10, fuel: "diesel" }), truck(2, "T2", { capacity: 12 })];

function renderGrid(onDone = vi.fn()) {
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <ToastProvider>
        <MemoryRouter>
          <RecordGrid type={TYPE as never} records={RECORDS as never} onDone={onDone} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const writes = () => mockFetch.mock.calls.filter(([, init]) => init?.method);

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (init?.method === "PATCH") return Promise.resolve({ ...truck(Number(path.split("/").pop()), body.key, body.attrs), updated_at: "new" });
    if (init?.method === "POST") return Promise.resolve(truck(99, body.key, body.attrs));
    if (init?.method === "DELETE") return Promise.resolve(null);
    return Promise.resolve({ items: [], total: 0 });
  });
  window.confirm = vi.fn(() => true);
});

describe("pastedCells", () => {
  it("splits an Excel block by line and tab", () => {
    expect(pastedCells("a\t1\r\nb\t2\r\n")).toEqual([["a", "1"], ["b", "2"]]);
  });
});

describe("RecordGrid", () => {
  it("saves only the rows that changed, with the timestamp each was read at", async () => {
    renderGrid();
    fireEvent.change(screen.getByLabelText("T2: capacity"), { target: { value: "15" } });
    expect(screen.getByRole("button", { name: "Save 1 change" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const [path, init] = writes()[0];
    expect(path).toBe("/api/v1/entities/2");
    expect(JSON.parse(String(init.body))).toEqual({ key: "T2", label: null, active: true, attrs: { capacity: 15 }, updated_at: "t2" });
    expect(await screen.findByRole("button", { name: "Save 0 changes" })).toBeDisabled();
  });

  it("keeps a shape it cannot show, so saving a row does not erase it", async () => {
    mockFetch.mockClear();
    const parked = { type: "Point", coordinates: [31, 30] };
    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <RecordGrid type={TYPE as never} records={[truck(3, "T3", { capacity: 1, parked })] as never} onDone={vi.fn()} />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    expect(screen.queryByLabelText("T3: parked")).toBeNull();
    fireEvent.change(screen.getByLabelText("T3: capacity"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(String(writes()[0][1].body)).attrs).toEqual({ capacity: 2, parked });
  });

  it("fills right and down from a pasted Excel block, adding rows, and creates them", async () => {
    renderGrid();
    fireEvent.paste(screen.getByLabelText("T2: key"), {
      clipboardData: { getData: () => "T2\tTruck two\nT3\tTruck three\nT4\tTruck four\n" },
    });
    expect(screen.getByLabelText("T2: label")).toHaveValue("Truck two");
    expect(screen.getByLabelText("T4: key")).toHaveValue("T4");
    fireEvent.click(screen.getByRole("button", { name: "Save 3 changes" }));
    await waitFor(() => expect(writes()).toHaveLength(3));
    expect(writes().map(([p, i]) => `${i.method} ${p}`)).toEqual([
      "PATCH /api/v1/entities/2", "POST /api/v1/entities", "POST /api/v1/entities",
    ]);
  });

  it("marks a bad row in place and still saves the good ones", async () => {
    renderGrid();
    fireEvent.change(screen.getByLabelText("T1: capacity"), { target: { value: "ten" } });
    fireEvent.change(screen.getByLabelText("T2: fuel"), { target: { value: "electric" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Add row" }));
    fireEvent.change(screen.getByLabelText("new row 3: label"), { target: { value: "no key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save 3 changes" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0][0]).toBe("/api/v1/entities/2");
    expect(within(screen.getAllByRole("alert")[0]).getByText(/capacity: must be a whole number/)).toBeInTheDocument();
    expect(screen.getByText("Key: required.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save 2 changes" })).toBeEnabled();
  });

  it("deletes marked rows after asking, and drops a new row without asking the server", async () => {
    renderGrid();
    fireEvent.click(screen.getByLabelText("Delete T1"));
    fireEvent.click(screen.getByRole("button", { name: "+ Add row" }));
    fireEvent.click(screen.getByLabelText("Delete new row 3"));
    fireEvent.click(screen.getByRole("button", { name: "Save 2 changes" }));
    expect(window.confirm).toHaveBeenCalledWith("Delete 1 record? This cannot be undone.");
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual(["/api/v1/entities/1", expect.objectContaining({ method: "DELETE" })]);
    await waitFor(() => expect(screen.queryByLabelText("T1: key")).toBeNull());
  });
});

describe("RecordGrid: shortcuts", () => {
  it("duplicates a row as a new one with its values and no key, right below it", async () => {
    renderGrid();
    fireEvent.click(screen.getByLabelText("Duplicate T1"));
    const copy = screen.getByTestId("grid-row-1");
    expect(within(copy).getByLabelText("new row 2: key")).toHaveValue("");
    expect(within(copy).getByLabelText("new row 2: capacity")).toHaveValue("10");
    expect(within(copy).getByLabelText("new row 2: fuel")).toHaveValue("diesel");
    fireEvent.change(within(copy).getByLabelText("new row 2: key"), { target: { value: "T1b" } });
    fireEvent.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(String(writes()[0][1].body))).toMatchObject({ key: "T1b", attrs: { capacity: 10, fuel: "diesel" } });
  });

  it("fills the parent into every new row, and runs what follows a create", async () => {
    const afterCreate = vi.fn(() => Promise.resolve());
    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <RecordGrid type={TYPE as never} records={[]} prefill={{ fuel: "electric" }} afterCreate={afterCreate} startWithNew />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    expect(screen.getByLabelText("new row 1: fuel")).toHaveValue("electric");
    expect(screen.getByRole("button", { name: "Save 0 changes" })).toBeDisabled(); // a prefilled row is not yet a change
    fireEvent.change(screen.getByLabelText("new row 1: key"), { target: { value: "T9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(afterCreate).toHaveBeenCalledWith(expect.objectContaining({ key: "T9" })));
  });
});
