import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityRecord, { entityServerErrors } from "./EntityRecord";
import { ToastProvider } from "../components/ToastProvider";
import { attrField } from "../components/AttrsForm";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

// Definition order is the API's (by name); the values below are chosen so
// that every JSON type an attr_type can produce is present, and so that the
// two values a form most often mangles -- a false boolean and a zero -- are
// among them.
const TYPE = {
  id: 5,
  domain_id: 7,
  name: "employee",
  role: "agent",
  attributes: [
    { id: 11, entity_type_id: 5, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
    { id: 12, entity_type_id: 5, name: "note", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
    { id: 13, entity_type_id: 5, name: "on_call", data_type: "boolean", required: false, unit: null, enum_values: null, default_value: null },
    { id: 14, entity_type_id: 5, name: "rate", data_type: "number", required: false, unit: "per hour", enum_values: null, default_value: null },
    { id: 15, entity_type_id: 5, name: "shift_kind", data_type: "enum", required: false, unit: null, enum_values: ["day", "night"], default_value: null },
    { id: 16, entity_type_id: 5, name: "start_date", data_type: "date", required: false, unit: null, enum_values: null, default_value: null },
    { id: 17, entity_type_id: 5, name: "start_time", data_type: "time", required: false, unit: null, enum_values: null, default_value: null },
  ],
};

const ENTITY = {
  id: 42,
  entity_type_id: 5,
  key: "ahmed",
  label: "Ahmed",
  sort_order: 3,
  active: true,
  attrs: {
    grade: 0,
    note: "",
    on_call: false,
    rate: 0,
    shift_kind: "day",
    start_date: "2026-09-19",
    start_time: "07:30",
    // Its definition was deleted after the entity was saved. The next PATCH
    // fails 422 unknown_attribute unless the form rebuilds `attrs` from
    // today's definitions (Task 11's probe, binding on this task).
    retired: "left over",
  },
};

function requests(): { path: string; method: string; body: any }[] {
  return mockFetch.mock.calls.map(([path, options]: any[]) => ({
    path: path as string,
    method: (options?.method as string) ?? "GET",
    body: options?.body ? JSON.parse(options.body as string) : undefined,
  }));
}

function writes() {
  return requests().filter((r) => r.method !== "GET");
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/entities" element={<p>entity list</p>} />
            <Route path="/entities/new" element={<EntityRecord />} />
            <Route path="/entities/:id" element={<EntityRecord />} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function reads(path: string) {
  mockFetch.mockImplementation((p: string) => {
    if (p === "/api/v1/entity-types/5") return Promise.resolve(TYPE);
    if (p === "/api/v1/entities/42") return Promise.resolve(ENTITY);
    return Promise.reject(new Error(`unexpected ${p}`));
  });
  return renderAt(path);
}

function setField(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function save(name: RegExp) {
  fireEvent.click(screen.getByRole("button", { name }));
}

beforeEach(() => {
  mockFetch.mockReset();
  window.confirm = vi.fn(() => true);
});

describe("EntityRecord: creating an entity", () => {
  async function openNew() {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
  }

  it("renders a control for every attribute of the type named in the query string", async () => {
    await openNew();
    for (const name of ["grade", "note", "on_call", "rate (per hour)", "shift_kind", "start_date", "start_time"]) {
      expect(screen.getByLabelText(name)).toBeInTheDocument();
    }
  });

  it("sends the key, the columns and every attribute with its JSON type intact", async () => {
    await openNew();
    setField(/^Key/, "ahmed");
    setField(/^Label/, "Ahmed");
    setField(/^Sort order/, "3");
    setField("grade", "0");
    setField("note", "0");
    setField("on_call", "false");
    setField("rate (per hour)", "0");
    setField("shift_kind", "night");
    setField("start_date", "2026-09-19");
    setField("start_time", "07:30");
    mockFetch.mockResolvedValueOnce({ ...ENTITY, attrs: {} });
    save(/create entity/i);

    await waitFor(() => expect(writes()).toHaveLength(1));
    const body = writes()[0].body;
    expect(writes()[0].method).toBe("POST");
    expect(body.entity_type_id).toBe(5);
    expect(body.key).toBe("ahmed");
    expect(body.attrs).toStrictEqual({
      grade: 0,
      note: "0",
      on_call: false,
      rate: 0,
      shift_kind: "night",
      start_date: "2026-09-19",
      start_time: "07:30",
    });
    expect(typeof body.attrs.grade).toBe("number");
    expect(typeof body.attrs.note).toBe("string");
    expect(typeof body.attrs.on_call).toBe("boolean");
    expect(body.sort_order).toBe(3);
  });

  it("omits an attribute left empty, so the server's default is materialised instead of being overwritten with null", async () => {
    await openNew();
    setField(/^Key/, "ahmed");
    mockFetch.mockResolvedValueOnce({ ...ENTITY, attrs: {} });
    save(/create entity/i);

    await waitFor(() => expect(writes()).toHaveLength(1));
    const body = writes()[0].body;
    expect(body.attrs).toStrictEqual({});
    // An untouched form's own columns: an empty label is an explicit null
    // (the column is nullable), not an empty string, and the two columns
    // with database defaults are sent as those defaults.
    expect(body.label).toBeNull();
    expect(body.sort_order).toBe(0);
    expect(body.active).toBe(true);
  });

  it("refuses an empty key without asking the server, even though the server would accept it", async () => {
    await openNew();
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("form-errors")).toBeInTheDocument());
    expect(writes()).toHaveLength(0);
    expect(screen.getByTestId("form-errors").textContent).toMatch(/key/i);
    expect(screen.getByLabelText(/^Key/)).toHaveAttribute("aria-invalid", "true");
  });

  it("refuses a whitespace-only key, which the server's missing CHECK would otherwise store", async () => {
    await openNew();
    setField(/^Key/, "   ");
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("form-errors")).toBeInTheDocument());
    expect(writes()).toHaveLength(0);
  });

  it("refuses a non-numeric entry in a number field client-side, sending nothing", async () => {
    await openNew();
    setField(/^Key/, "ahmed");
    setField("rate (per hour)", "banana");
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("form-errors")).toBeInTheDocument());
    expect(writes()).toHaveLength(0);
    expect(screen.getByLabelText("rate (per hour)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("form-errors").textContent).toContain("rate: must be a number");
  });

  it("blocks submit on an empty required attribute before the server sees it", async () => {
    mockFetch.mockImplementation((p: string) => {
      if (p === "/api/v1/entity-types/5") {
        return Promise.resolve({
          ...TYPE,
          attributes: [{ ...TYPE.attributes[0], required: true }],
        });
      }
      return Promise.reject(new Error(`unexpected ${p}`));
    });
    renderAt("/entities/new?type=5");
    expect(await screen.findByLabelText(/^grade/)).toBeInTheDocument();
    setField(/^Key/, "ahmed");
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("form-errors")).toBeInTheDocument());
    expect(writes()).toHaveLength(0);
    expect(screen.getByLabelText(/^grade/)).toHaveAttribute("aria-invalid", "true");
  });

  it("goes to the saved entity once the server accepts it", async () => {
    await openNew();
    setField(/^Key/, "ahmed");
    mockFetch.mockResolvedValueOnce({ ...ENTITY, id: 99, attrs: {} });
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/entities/99"));
  });

  it("asks for an entity type when the query string names none", async () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error("no request expected")));
    renderAt("/entities/new");
    expect(await screen.findByText(/choose an entity type/i)).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });
});

describe("EntityRecord: editing an entity", () => {
  async function openEdit() {
    reads("/entities/42");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
  }

  it("fills each control from the stored value, keeping a false boolean, a zero and an empty text visible", async () => {
    await openEdit();
    expect((screen.getByLabelText(/^Key/) as HTMLInputElement).value).toBe("ahmed");
    expect((screen.getByLabelText(/^Sort order/) as HTMLInputElement).value).toBe("3");
    expect((screen.getByLabelText("grade") as HTMLInputElement).value).toBe("0");
    expect((screen.getByLabelText("rate (per hour)") as HTMLInputElement).value).toBe("0");
    expect((screen.getByLabelText("note") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("on_call") as HTMLSelectElement).value).toBe("false");
    expect((screen.getByLabelText("shift_kind") as HTMLSelectElement).value).toBe("day");
    expect((screen.getByLabelText("start_date") as HTMLInputElement).value).toBe("2026-09-19");
    expect((screen.getByLabelText("start_time") as HTMLInputElement).value).toBe("07:30");
    expect((screen.getByLabelText(/^Active/) as HTMLInputElement).checked).toBe(true);
  });

  it("round-trips the loaded values through a save, keeping a zero and a false", async () => {
    await openEdit();
    mockFetch.mockResolvedValueOnce(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    const body = writes()[0].body;
    expect(writes()[0].method).toBe("PATCH");
    expect(writes()[0].path).toBe("/api/v1/entities/42");
    // `note` is the one exception, and it is deliberate: an empty control
    // means "not provided" for every attr_type, so the stored empty string
    // becomes an absent key. See the next test.
    expect(body.attrs).toStrictEqual({
      grade: 0,
      on_call: false,
      rate: 0,
      shift_kind: "day",
      start_date: "2026-09-19",
      start_time: "07:30",
    });
    expect(typeof body.attrs.grade).toBe("number");
    expect(typeof body.attrs.on_call).toBe("boolean");
    expect(body.key).toBe("ahmed");
    expect(body.label).toBe("Ahmed");
    expect(body.sort_order).toBe(3);
    expect(body.active).toBe(true);
  });

  it("turns a stored empty string into an absent key, because an empty control means 'not provided' for every type", async () => {
    await openEdit();
    expect((screen.getByLabelText("note") as HTMLInputElement).value).toBe("");
    mockFetch.mockResolvedValueOnce(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.attrs).not.toHaveProperty("note");
  });

  it("re-seeds the controls from what the server stored, so a materialised default appears without a reload", async () => {
    await openEdit();
    mockFetch.mockResolvedValueOnce({ ...ENTITY, attrs: { ...ENTITY.attrs, grade: 7, retired: undefined } });
    save(/save entity/i);
    await waitFor(() => expect((screen.getByLabelText("grade") as HTMLInputElement).value).toBe("7"));
  });

  it("drops a stored key whose attribute definition was deleted, rebuilding attrs rather than merging it", async () => {
    await openEdit();
    mockFetch.mockResolvedValueOnce(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.attrs).not.toHaveProperty("retired");
  });

  it("warns on screen that the stale key will be removed, naming it", async () => {
    await openEdit();
    expect(screen.getByTestId("stale-attrs").textContent).toContain("retired");
  });

  it("clears an attribute by emptying its control, which removes the key rather than sending null", async () => {
    await openEdit();
    setField("shift_kind", "");
    mockFetch.mockResolvedValueOnce(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.attrs).not.toHaveProperty("shift_kind");
    expect(Object.values(writes()[0].body.attrs)).not.toContain(null);
  });

  it("deletes the entity after a confirmation and returns to the list", async () => {
    await openEdit();
    mockFetch.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole("button", { name: /delete entity/i }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].method).toBe("DELETE");
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/entities"));
  });

  it("does not delete when the confirmation is dismissed", async () => {
    await openEdit();
    window.confirm = vi.fn(() => false);
    fireEvent.click(screen.getByRole("button", { name: /delete entity/i }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(writes()).toHaveLength(0);
  });

  it("says so when the entity does not exist, rather than offering to retry a request that will 404 again", async () => {
    mockFetch.mockImplementation(() => Promise.reject(new ApiError(404, JSON.stringify({ detail: "entity not found" }))));
    renderAt("/entities/42");
    expect(await screen.findByText("Entity not found.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to entities/i })).toHaveAttribute("href", "/entities");
  });

  it("says not found for an id that is not a bigint key, without asking the server for it", async () => {
    mockFetch.mockImplementation((p: string) => Promise.reject(new Error(`unexpected ${p}`)));
    renderAt("/entities/not-an-id");
    expect(await screen.findByText("Entity not found.")).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("EntityRecord: a refusal from the server", () => {
  async function openNew() {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
    setField(/^Key/, "ahmed");
  }

  function refuse(body: unknown, status = 422) {
    mockFetch.mockRejectedValueOnce(new ApiError(status, JSON.stringify(body)));
  }

  it("marks the named attribute and announces the message in the live region", async () => {
    await openNew();
    refuse({
      detail: [{ type: "value_error", loc: ["body", "grade"], msg: 'entity ahmed: attribute "grade" is required', kind: "required_attribute" }],
    });
    save(/create entity/i);

    const summary = await screen.findByTestId("form-errors");
    expect(summary).toHaveAttribute("role", "alert");
    expect(summary.textContent).toContain('attribute "grade" is required');
    expect(screen.getByLabelText("grade")).toHaveAttribute("aria-invalid", "true");
  });

  it("marks the attribute named by an attribute_type refusal", async () => {
    await openNew();
    refuse({
      detail: [{ type: "value_error", loc: ["body", "on_call"], msg: 'entity ahmed: attribute "on_call" must be boolean', kind: "attribute_type" }],
    });
    save(/create entity/i);
    await waitFor(() => expect(screen.getByLabelText("on_call")).toHaveAttribute("aria-invalid", "true"));
  });

  it("marks the key field when the key is already taken", async () => {
    await openNew();
    refuse({ detail: "a entity row with the same type_id already exists" }, 409);
    save(/create entity/i);
    await waitFor(() => expect(screen.getByLabelText(/^Key/)).toHaveAttribute("aria-invalid", "true"));
    expect((await screen.findByTestId("form-errors")).textContent).toMatch(/key/i);
  });
});

describe("entityServerErrors", () => {
  const names = ["grade", "on_call"];
  const err = (status: number, body: unknown) => new ApiError(status, JSON.stringify(body));

  it("routes a trigger's attribute refusal to that attribute's control", () => {
    const result = entityServerErrors(
      err(422, { detail: [{ loc: ["body", "grade"], msg: "bad grade", kind: "attribute_type" }] }),
      names
    );
    expect(result.fields).toStrictEqual({ [attrField("grade")]: "bad grade" });
    expect(result.general).toBeNull();
  });

  it("routes a column refusal to that column, not to an attribute of the same name", () => {
    const result = entityServerErrors(err(422, { detail: [{ loc: ["body", "key"], msg: "bad key" }] }), names);
    expect(result.fields).toStrictEqual({ key: "bad key" });
  });

  it("does not mistake a column error for an attribute when an attribute shares the column's name", () => {
    // `key` is both a column and a legal attribute name; `kind` is the only
    // discriminator the wire carries (Ruling 19). Both directions matter, so
    // both are asserted with the same field name and the same `fields` list.
    const fromTrigger = entityServerErrors(
      err(422, { detail: [{ loc: ["body", "key"], msg: "from the trigger", kind: "attribute_type" }] }),
      ["key"]
    );
    expect(fromTrigger.fields).toStrictEqual({ [attrField("key")]: "from the trigger" });

    const fromRequestLayer = entityServerErrors(err(422, { detail: [{ loc: ["body", "key"], msg: "from Pydantic" }] }), ["key"]);
    expect(fromRequestLayer.fields).toStrictEqual({ key: "from Pydantic" });
  });

  it("shows an unknown_attribute refusal as a general message rather than dropping it", () => {
    const result = entityServerErrors(
      err(422, { detail: [{ loc: ["body", "retired"], msg: 'unknown attribute "retired"', kind: "unknown_attribute" }] }),
      names
    );
    expect(result.fields).toStrictEqual({});
    expect(result.general).toContain("retired");
  });

  it("keeps an unknown_attribute general even when the loaded type still lists that name", () => {
    // The definition was deleted after this page loaded its type, so the
    // client believes in a control the server has just refused by name. The
    // server is the authority: attaching the message to a control that is
    // about to disappear would hide it.
    const result = entityServerErrors(
      err(422, { detail: [{ loc: ["body", "grade"], msg: 'unknown attribute "grade"', kind: "unknown_attribute" }] }),
      names
    );
    expect(result.fields).toStrictEqual({});
    expect(result.general).toContain("grade");
  });

  it("sends a 409 about a duplicate key to the key field", () => {
    const result = entityServerErrors(err(409, { detail: "a entity row with the same type_id already exists" }), names);
    expect(Object.keys(result.fields)).toEqual(["key"]);
    expect(result.general).toBeNull();
  });

  it("leaves any other failure as a general message", () => {
    const result = entityServerErrors(err(500, { detail: "boom" }), names);
    expect(result.fields).toStrictEqual({});
    expect(result.general).toBeTruthy();
  });
});
