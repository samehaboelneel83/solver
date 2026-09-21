import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EntityTypeDetail from "./EntityTypeDetail";
import { ToastProvider } from "../components/ToastProvider";
import type { EntityType } from "../api/v1";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const TYPE: EntityType = {
  id: 5,
  domain_id: 7,
  name: "employee",
  role: "agent",
  colour: null,
  updated_at: "2026-09-20T09:00:00+00:00",
  attributes: [
    { id: 11, entity_type_id: 5, name: "grade", data_type: "integer", required: true, unit: "level", enum_values: null, default_value: 3 },
    { id: 12, entity_type_id: 5, name: "on_call", data_type: "boolean", required: false, unit: null, enum_values: null, default_value: false },
    { id: 13, entity_type_id: 5, name: "shift_kind", data_type: "enum", required: false, unit: null, enum_values: ["day", "night"], default_value: null },
  ],
};

type Handler = (path: string, init?: RequestInit) => Promise<unknown> | undefined;

/** GETs of the type always answer with TYPE; `write` decides every other call. */
function serve(write: Handler = () => undefined) {
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      const answer = write(path, init);
      if (answer) return answer;
      return Promise.reject(new Error(`unexpected ${method} ${path}`));
    }
    if (path === "/api/v1/entity-types/5") return Promise.resolve(TYPE);
    return Promise.reject(new ApiError(404, JSON.stringify({ detail: "entity type not found" })));
  });
}

function writes(): { method: string; path: string; body: unknown }[] {
  return mockFetch.mock.calls
    .filter((call) => (call[1] as RequestInit | undefined)?.method && (call[1] as RequestInit).method !== "GET")
    .map((call) => {
      const init = call[1] as RequestInit;
      return { method: init.method as string, path: call[0] as string, body: init.body ? JSON.parse(init.body as string) : undefined };
    });
}

/** Lets any pending request the click started actually reach apiFetch, so
 * "nothing was sent" is a real observation and not just a synchronous one. */
function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(path = "/entity-types/5") {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/entity-types" element={<p>list page</p>} />
            <Route path="/entity-types/:id" element={<EntityTypeDetail />} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

async function loaded() {
  await screen.findByRole("heading", { level: 1, name: /employee/ });
}

function typeForm() {
  return screen.getByRole("form", { name: "Entity type" });
}

function attributesTable() {
  return screen.getByRole("table", { name: "Attributes" });
}

function rowFor(name: string) {
  const row = within(attributesTable())
    .getAllByRole("row")
    .find((r) => within(r).queryByText(name, { selector: "th, td" }));
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

describe("EntityTypeDetail", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the type and its attributes together, with each default in its own type", async () => {
    serve();
    renderPage();
    await loaded();

    expect(within(typeForm()).getByLabelText(/^Name/)).toHaveValue("employee");
    expect(within(typeForm()).getByLabelText(/^Role/)).toHaveValue("agent");

    const grade = rowFor("grade");
    expect(within(grade).getByText("Integer")).toBeInTheDocument();
    expect(within(grade).getByText("3")).toBeInTheDocument();
    expect(within(grade).getByText("level")).toBeInTheDocument();
    expect(within(grade).getByText("Yes")).toBeInTheDocument();
    // `on_call`'s type is "Yes / no", so its default is No -- not "False",
    // which is a vocabulary this table alone used to speak.
    // Read by POSITION: the Required column says "No" on this row too, so
    // "somewhere on the row it says No" would pass against the old "False".
    // The name is a <th scope="row">, so the cells start at Data type.
    const onCall = within(rowFor("on_call")).getAllByRole("cell");
    expect(onCall[0]).toHaveTextContent("Yes / no");
    expect(onCall[4]).toHaveTextContent(/^No$/);
    expect(rowFor("on_call").textContent).not.toContain("False");
    const kind = rowFor("shift_kind");
    expect(within(kind).getByText("day, night")).toBeInTheDocument();
    expect(within(kind).getByText("No default")).toBeInTheDocument();
  });

  it("saves the type's own fields with PATCH and confirms with a toast", async () => {
    serve((path, init) => (init?.method === "PATCH" && path === "/api/v1/entity-types/5" ? Promise.resolve({ ...TYPE, name: "staff" }) : undefined));
    renderPage();
    await loaded();

    fireEvent.change(within(typeForm()).getByLabelText(/^Name/), { target: { value: "staff" } });
    fireEvent.change(within(typeForm()).getByLabelText(/^Role/), { target: { value: "resource" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "PATCH",
      path: "/api/v1/entity-types/5",
      // Ruling 42: the `updated_at` the form read goes back with every
      // save, so the server can refuse one built on a superseded read.
      body: { name: "staff", role: "resource", colour: null, updated_at: "2026-09-20T09:00:00+00:00" },
    });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/entity type saved/i));
  });

  it("marks the field a 422 names on the type form, not the other one", async () => {
    serve((_path, init) =>
      init?.method === "PATCH"
        ? Promise.reject(new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "role"], msg: "Input should be 'agent'", type: "literal_error" }] })))
        : undefined
    );
    renderPage();
    await loaded();
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    const role = within(typeForm()).getByLabelText(/^Role/);
    await waitFor(() => expect(role).toHaveAttribute("aria-invalid", "true"));
    expect(role).toHaveAccessibleDescription(/Input should be 'agent'/);
    expect(within(typeForm()).getByLabelText(/^Name/)).not.toHaveAttribute("aria-invalid");
  });

  it("shows a duplicate-name 409 on the type's name field", async () => {
    serve((_path, init) =>
      init?.method === "PATCH"
        ? Promise.reject(new ApiError(409, JSON.stringify({ detail: "a entity_type row with the same domain_id_name already exists" })))
        : undefined
    );
    renderPage();
    await loaded();
    fireEvent.change(within(typeForm()).getByLabelText(/^Name/), { target: { value: "shift" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    const name = within(typeForm()).getByLabelText(/^Name/);
    await waitFor(() => expect(name).toHaveAttribute("aria-invalid", "true"));
    expect(name).toHaveAccessibleDescription(/already has an entity type with this name/i);
  });

  it("adds an attribute to this type with a typed default", async () => {
    serve((path, init) =>
      init?.method === "POST" && path === "/api/v1/entity-types/5/attributes"
        ? Promise.resolve({ id: 20, entity_type_id: 5, name: "hours", data_type: "integer", required: false, unit: null, enum_values: null, default_value: 8 })
        : undefined
    );
    renderPage();
    await loaded();

    fireEvent.click(screen.getByRole("button", { name: "Add attribute" }));
    const editor = screen.getByRole("form", { name: "New attribute" });
    fireEvent.change(within(editor).getByLabelText(/^Name/), { target: { value: "hours" } });
    fireEvent.change(within(editor).getByLabelText(/^Data type/), { target: { value: "integer" } });
    fireEvent.change(within(editor).getByLabelText(/^Default value/), { target: { value: "8" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add attribute" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "POST",
      path: "/api/v1/entity-types/5/attributes",
      body: { name: "hours", data_type: "integer", required: false, unit: null, enum_values: null, default_value: 8 },
    });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/attribute "hours" added/i));
    await waitFor(() => expect(screen.queryByRole("form", { name: "New attribute" })).not.toBeInTheDocument());
  });

  it("does not send an integer default of 2.5", async () => {
    serve();
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Add attribute" }));
    const editor = screen.getByRole("form", { name: "New attribute" });
    fireEvent.change(within(editor).getByLabelText(/^Name/), { target: { value: "hours" } });
    fireEvent.change(within(editor).getByLabelText(/^Data type/), { target: { value: "integer" } });
    fireEvent.change(within(editor).getByLabelText(/^Default value/), { target: { value: "2.5" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add attribute" }));

    expect(within(editor).getByLabelText(/^Default value/)).toHaveAttribute("aria-invalid", "true");
    expect(writes()).toEqual([]);
  });

  it("puts a 422 on the attribute field it names, with the other fields on screen", async () => {
    serve((_path, init) =>
      init?.method === "POST"
        ? Promise.reject(
            new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "enum_values"], msg: "an attribute of type 'enum' must list its allowed values", type: "value_error" }] }))
          )
        : undefined
    );
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Add attribute" }));
    const editor = screen.getByRole("form", { name: "New attribute" });
    fireEvent.change(within(editor).getByLabelText(/^Name/), { target: { value: "level" } });
    fireEvent.change(within(editor).getByLabelText(/^Data type/), { target: { value: "enum" } });
    fireEvent.change(within(editor).getByLabelText(/^Allowed values/), { target: { value: "low\nhigh" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add attribute" }));

    const values = within(editor).getByLabelText(/^Allowed values/);
    await waitFor(() => expect(values).toHaveAttribute("aria-invalid", "true"));
    expect(values).toHaveAccessibleDescription(/must list its allowed values/);
    for (const other of [/^Name/, /^Data type/, /^Unit/, /^Default value/]) {
      expect(within(editor).getByLabelText(other)).not.toHaveAttribute("aria-invalid");
    }
  });

  it("shows a duplicate attribute name 409 on the attribute's name field", async () => {
    serve((_path, init) =>
      init?.method === "POST"
        ? Promise.reject(new ApiError(409, JSON.stringify({ detail: "a attribute_def row with the same entity_type_id_name already exists" })))
        : undefined
    );
    renderPage();
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Add attribute" }));
    const editor = screen.getByRole("form", { name: "New attribute" });
    fireEvent.change(within(editor).getByLabelText(/^Name/), { target: { value: "grade" } });
    fireEvent.change(within(editor).getByLabelText(/^Data type/), { target: { value: "text" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Add attribute" }));

    const name = within(editor).getByLabelText(/^Name/);
    await waitFor(() => expect(name).toHaveAttribute("aria-invalid", "true"));
    expect(name).toHaveAccessibleDescription(/already has an attribute with this name/i);
  });

  it("edits an attribute in place with PATCH, showing the materialised-default note", async () => {
    serve((path, init) => (init?.method === "PATCH" && path === "/api/v1/attributes/11" ? Promise.resolve({ ...TYPE.attributes[0], default_value: 4 }) : undefined));
    renderPage();
    await loaded();

    fireEvent.click(within(rowFor("grade")).getByRole("button", { name: "Edit grade" }));
    const editor = screen.getByRole("form", { name: "Edit attribute grade" });
    const def = within(editor).getByLabelText(/^Default value/);
    expect(def).toHaveValue("3");
    expect(def).toHaveAccessibleDescription(/existing entities keep the default they were given/i);

    fireEvent.change(def, { target: { value: "4" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save attribute" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "PATCH",
      path: "/api/v1/attributes/11",
      body: { name: "grade", data_type: "integer", required: true, unit: "level", enum_values: null, default_value: 4 },
    });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/attribute "grade" saved/i));
  });

  it("deletes an attribute only after a confirmation that says what happens to stored values", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    serve((path, init) => (init?.method === "DELETE" && path === "/api/v1/attributes/13" ? Promise.resolve(null) : undefined));
    renderPage();
    await loaded();

    fireEvent.click(within(rowFor("shift_kind")).getByRole("button", { name: "Delete shift_kind" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toMatch(/shift_kind/);
    expect(confirm.mock.calls[0][0]).toMatch(/values already stored on entities are not removed/i);
    await flush();
    expect(writes()).toEqual([]);
  });

  describe("deleting the type", () => {
    it("names everything that goes with it in the confirmation, and does nothing on cancel", async () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      serve();
      renderPage();
      await loaded();

      fireEvent.click(screen.getByRole("button", { name: "Delete entity type" }));
      const text = confirm.mock.calls[0][0] as string;
      expect(text).toMatch(/"employee"/);
      expect(text).toMatch(/its 3 attribute definitions/);
      expect(text).toMatch(/every entity of this type/);
      expect(text).toMatch(/relationship types that use it, and their relationships/);
      expect(text).toMatch(/parameters indexed by it are not deleted/i);
      expect(text).toMatch(/cannot be undone/);
      await flush();
      expect(writes()).toEqual([]);
    });

    it("deletes on confirm, toasts, and returns to the list", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      serve((path, init) => (init?.method === "DELETE" && path === "/api/v1/entity-types/5" ? Promise.resolve(null) : undefined));
      renderPage();
      await loaded();

      fireEvent.click(screen.getByRole("button", { name: "Delete entity type" }));
      await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/entity-types$/));
      expect(writes()).toEqual([{ method: "DELETE", path: "/api/v1/entity-types/5", body: undefined }]);
      await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/entity type "employee" deleted/i));
    });
  });

  it("says the type was not found on a 404", async () => {
    serve();
    renderPage("/entity-types/999");
    expect(await screen.findByText(/entity type not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to entity types/i })).toHaveAttribute("href", "/entity-types");
    // Every other state of this page has one; without it here the page has
    // no level-1 heading at all, which is an axe `page-has-heading-one`
    // violation and leaves a screen-reader user with nothing to land on.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/entity type not found/i);
  });

  // --- Task 14b: colour --------------------------------------------------

  it("seeds the colour control from the stored value and saves a change", async () => {
    serve((path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, colour: "#ff8800" }) : undefined));
    renderPage();
    await loaded();

    expect(within(typeForm()).getByTestId("colour-hex")).toHaveValue("");
    fireEvent.change(within(typeForm()).getByTestId("colour-hex"), { target: { value: "#FF8800" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "PATCH",
      path: "/api/v1/entity-types/5",
      // Lower case, whatever was typed: the column only ever holds that form.
      body: { name: "employee", role: "agent", colour: "#ff8800", updated_at: "2026-09-20T09:00:00+00:00" },
    });
  });

  it("clears a colour back to automatic", async () => {
    serve((path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, colour: null }) : undefined));
    renderPage();
    await loaded();

    fireEvent.change(within(typeForm()).getByTestId("colour-hex"), { target: { value: "#ff8800" } });
    fireEvent.click(within(typeForm()).getByTestId("colour-clear"));
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect((writes()[0].body as Record<string, unknown>).colour).toBeNull();
  });

  /*
   * This used to send the PATCH anyway, carrying the last good colour, and
   * toast "Entity type saved" -- the one field in the product that reported
   * success while dropping what the user typed. It now blocks the save like
   * every other invalid field, and says so in the same error summary.
   */
  it("refuses a malformed hex without sending anything", async () => {
    serve();
    renderPage();
    await loaded();

    fireEvent.change(within(typeForm()).getByTestId("colour-hex"), { target: { value: "#zzz" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));
    await flush();
    expect(writes()).toHaveLength(0);
    // Both places every other refused field appears: the summary at the
    // top of the form, and the text under the control itself.
    expect(within(typeForm()).getByTestId("form-errors")).toHaveTextContent(
      /Colour: Use a six-digit hex colour/i
    );
    expect(within(typeForm()).getByTestId("colour-hex")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("Entity type saved")).not.toBeInTheDocument();
  });

  it("saves once the colour is corrected, with the error gone", async () => {
    serve((path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, colour: "#00aa00" }) : undefined));
    renderPage();
    await loaded();

    fireEvent.change(within(typeForm()).getByTestId("colour-hex"), { target: { value: "banana" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));
    await flush();
    expect(writes()).toHaveLength(0);

    fireEvent.change(within(typeForm()).getByTestId("colour-hex"), { target: { value: "#00aa00" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect((writes()[0].body as Record<string, unknown>).colour).toBe("#00aa00");
    expect(within(typeForm()).queryByTestId("form-errors")).not.toBeInTheDocument();
  });
});

describe("EntityTypeDetail: a concurrent edit (Ruling 42)", () => {
  const STALE = new ApiError(409, JSON.stringify({ detail: "This entity type was changed by someone else after this form loaded it. Reload the entity type and apply your changes to the current version." }));
  /** What the other client left behind: a different role and a colour. */
  const CHANGED: EntityType = {
    ...TYPE,
    role: "resource",
    colour: "#ff8800",
    updated_at: "2026-09-20T09:05:00+00:00",
  };

  function answerGetsWith(type: EntityType) {
    mockFetch.mockImplementation((path: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") !== "GET") return Promise.reject(STALE);
      if (path === "/api/v1/entity-types/5") return Promise.resolve(type);
      return Promise.reject(new ApiError(404, JSON.stringify({ detail: "entity type not found" })));
    });
  }

  it("refuses with a reload offer rather than a field error", async () => {
    answerGetsWith(TYPE);
    renderPage();
    await loaded();
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));

    const notice = await screen.findByTestId("stale-record");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice.textContent).toContain("changed by someone else");
    expect(within(typeForm()).getByLabelText(/^Name/)).not.toHaveAttribute("aria-invalid");
  });

  it("keeps the name being typed and takes the other client's role", async () => {
    answerGetsWith(TYPE);
    renderPage();
    await loaded();
    fireEvent.change(within(typeForm()).getByLabelText(/^Name/), { target: { value: "staff" } });
    fireEvent.click(within(typeForm()).getByRole("button", { name: "Save entity type" }));
    await screen.findByTestId("stale-record");

    answerGetsWith(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));

    await waitFor(() => expect(within(typeForm()).getByLabelText(/^Role/)).toHaveValue("resource"));
    expect(within(typeForm()).getByLabelText(/^Name/)).toHaveValue("staff");
    expect(screen.queryByTestId("stale-record")).toBeNull();
  });
});
