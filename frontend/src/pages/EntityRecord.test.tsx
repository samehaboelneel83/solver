import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityRecord, { entityServerErrors } from "./EntityRecord";
import { ToastProvider } from "../components/ToastProvider";
import { attrField } from "../components/AttrsForm";
import { editorQueryClient } from "../test/me";

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
  // Migration 0010 (Ruling 42). Every entity read carries it; the form
  // sends it back so a save built on a superseded read is refused.
  updated_at: "2026-09-20T09:00:00+00:00",
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
  const queryClient = editorQueryClient();
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

/** The domain around this entity, for the Relationships section: one
 * cross-type relationship (employee -> unit) and the unit it points at.
 * `works_in` is `many_to_one`, which is what makes the cardinality
 * refusal below a real one. */
const ENTITY_TYPES = [
  TYPE,
  { id: 9, domain_id: 7, name: "unit", role: "org", colour: null, attributes: [], updated_at: "t" },
];
const REL_TYPES = [
  {
    id: 3,
    domain_id: 7,
    name: "works_in",
    from_type_id: 5,
    to_type_id: 9,
    cardinality: "many_to_one",
    is_hierarchy: false,
    colour: null,
    updated_at: "t",
  },
  // An INCOMING type: this employee is the To end. Without one, a section
  // that only ever asked `from_entity_id=` would look complete.
  {
    id: 4,
    domain_id: 7,
    name: "manages",
    from_type_id: 9,
    to_type_id: 5,
    cardinality: "many_to_many",
    is_hierarchy: false,
    colour: null,
    updated_at: "t",
  },
];
const UNITS = [
  { id: 71, entity_type_id: 9, key: "north", label: "North Depot", sort_order: 0, active: true, attrs: {}, updated_at: "t" },
  { id: 72, entity_type_id: 9, key: "south", label: "South Depot", sort_order: 1, active: true, attrs: {}, updated_at: "t" },
];
const OUTGOING = [
  { id: 301, relationship_type_id: 3, from_entity_id: 42, to_entity_id: 71, attrs: {}, valid_from: null, valid_to: null },
];
const INCOMING = [
  { id: 302, relationship_type_id: 4, from_entity_id: 72, to_entity_id: 42, attrs: {}, valid_from: null, valid_to: null },
];

/*
 * What the next write, and the next read of this entity, answer.
 *
 * These used to be `mockResolvedValueOnce`, which queues an answer for
 * WHICHEVER request comes next. That was safe while the page made two
 * requests it fully controlled; the Relationships section adds background
 * reads, and a mutation invalidates them all, so "the next request" is no
 * longer "the save". Both answers are therefore addressed by what they
 * answer, not by their position in a queue.
 */
let writeAnswer: unknown = null;
let entityAnswer: unknown = null;

function answerWrite(value: unknown) {
  writeAnswer = Promise.resolve(value);
}
function refuseWrite(error: unknown) {
  writeAnswer = Promise.reject(error);
  // A rejected promise nobody has awaited yet is an unhandled rejection
  // in node until the component gets to it; this keeps the run quiet.
  (writeAnswer as Promise<unknown>).catch(() => {});
}
function answerEntity(value: unknown) {
  entityAnswer = value;
}

// The record's place in self-nesting relationships: none unless a test gives one.
let treesAnswer: unknown = { entity_id: 42, trees: [] };
let referrersAnswer: unknown = { entity_id: 42, fields: [], blocks_delete: false };

function reads(path: string) {
  mockFetch.mockImplementation((p: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") {
      if (writeAnswer) {
        const answer = writeAnswer;
        // One write per answer, as `...Once` gave: a second save in the
        // same test must set its own.
        writeAnswer = null;
        return answer;
      }
      return Promise.reject(new Error(`unexpected ${init.method} ${p}`));
    }
    if (p === "/api/v1/entity-types/5") return Promise.resolve(TYPE);
    if (p === "/api/v1/entities/42") return Promise.resolve(entityAnswer ?? ENTITY);
    if (p === "/api/v1/entities/42/trees") return Promise.resolve(treesAnswer);
    if (p === "/api/v1/entities/42/referrers") return Promise.resolve(referrersAnswer);
    if (p.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
    if (p.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: REL_TYPES, total: 1 });
    if (p.startsWith("/api/v1/relationships")) {
      if (p.includes("from_entity_id=42")) return Promise.resolve({ items: OUTGOING, total: 1 });
      if (p.includes("to_entity_id=42")) return Promise.resolve({ items: INCOMING, total: 1 });
      return Promise.resolve({ items: [], total: 0 });
    }
    if (p.startsWith("/api/v1/entities")) {
      if (p.includes("entity_type_id=9")) return Promise.resolve({ items: UNITS, total: 2 });
      return Promise.resolve({ items: [], total: 0 });
    }
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
  writeAnswer = null;
  entityAnswer = null;
  treesAnswer = { entity_id: 42, trees: [] };
  referrersAnswer = { entity_id: 42, fields: [], blocks_delete: false };
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
    answerWrite({ ...ENTITY, attrs: {} });
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
    answerWrite({ ...ENTITY, attrs: {} });
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
    answerWrite({ ...ENTITY, id: 99, attrs: {} });
    save(/create entity/i);
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/entities/99"));
  });

  it("asks for an entity type when the query string names none", async () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error("no request expected")));
    renderAt("/entities/new");
    expect(await screen.findByText(/choose an entity type/i)).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
    // Reachable by typing or bookmarking /entities/new, and it had no
    // level-1 heading: an axe `page-has-heading-one` violation.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/new entity/i);
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
    answerWrite(ENTITY);
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
    answerWrite(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.attrs).not.toHaveProperty("note");
  });

  it("re-seeds the controls from what the server stored, so a materialised default appears without a reload", async () => {
    await openEdit();
    answerWrite({ ...ENTITY, attrs: { ...ENTITY.attrs, grade: 7, retired: undefined } });
    save(/save entity/i);
    await waitFor(() => expect((screen.getByLabelText("grade") as HTMLInputElement).value).toBe("7"));
  });

  it("drops a stored key whose attribute definition was deleted, rebuilding attrs rather than merging it", async () => {
    await openEdit();
    answerWrite(ENTITY);
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
    answerWrite(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.attrs).not.toHaveProperty("shift_kind");
    expect(Object.values(writes()[0].body.attrs)).not.toContain(null);
  });

  it("deletes the entity after a confirmation and returns to the list", async () => {
    await openEdit();
    answerWrite(undefined);
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
    // Same page, no level-1 heading: an axe `page-has-heading-one`
    // violation, and nothing for a screen-reader user to land on.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Entity not found.");
  });

  it("says not found for an id that is not a bigint key, without asking the server for it", async () => {
    mockFetch.mockImplementation((p: string) => Promise.reject(new Error(`unexpected ${p}`)));
    renderAt("/entities/not-an-id");
    expect(await screen.findByText("Entity not found.")).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("EntityRecord: deep link to the graph (B-3)", () => {
  it("links to the graph focused on this entity, in the entity's own domain", async () => {
    // Domain 7, type 5 and entity 42 are all different, so a link built from
    // the wrong id cannot pass by coincidence. The domain comes from the
    // entity's *type* -- entities carry no domain of their own -- because
    // the graph only looks for the focused node in the domain it has loaded.
    reads("/entities/42");

    const link = await screen.findByRole("link", { name: /open in graph/i });
    expect(link).toHaveAttribute("href", "/graph?domain=7&focus=42");
  });

  it("offers no graph link for an entity that has not been created yet", async () => {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();

    expect(screen.queryByRole("link", { name: /open in graph/i })).not.toBeInTheDocument();
  });
});

describe("EntityRecord: a refusal from the server", () => {
  async function openNew() {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
    setField(/^Key/, "ahmed");
  }

  function refuse(body: unknown, status = 422) {
    refuseWrite(new ApiError(status, JSON.stringify(body)));
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

describe("EntityRecord: a concurrent edit (Ruling 42)", () => {
  const STALE = {
    detail:
      "This entity was changed by someone else after this form loaded it. " +
      "Reload the entity and apply your changes to the current version.",
  };

  async function openEdit() {
    reads("/entities/42");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
  }

  /** What the other client left behind: a different label and two
   * different attribute values, and a moved `updated_at`. */
  const CHANGED = {
    ...ENTITY,
    label: "Ahmed (changed by the other client)",
    attrs: { ...ENTITY.attrs, grade: 9, note: "written by the other client" },
    updated_at: "2026-09-20T09:05:00+00:00",
  };

  it("sends the updated_at it read, which is what lets the server refuse", async () => {
    await openEdit();
    answerWrite(ENTITY);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body.updated_at).toBe(ENTITY.updated_at);
  });

  it("does not send updated_at when creating, because there is nothing to compare", async () => {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
    setField(/^Key/, "ahmed");
    answerWrite({ ...ENTITY, id: 99 });
    save(/create entity/i);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).not.toHaveProperty("updated_at");
  });

  it("shows the refusal with a way out instead of a red line under a control", async () => {
    await openEdit();
    refuseWrite(new ApiError(409, JSON.stringify(STALE)));
    setField(/^Label/, "Ahmed (edited here)");
    save(/save entity/i);

    const notice = await screen.findByTestId("stale-record");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice.textContent).toContain("changed by someone else");
    expect(within(notice).getByRole("button", { name: /reload and keep my changes/i })).toBeInTheDocument();
    // Not a field error: nothing in the payload is wrong, so nothing is
    // marked invalid and the summary stays empty.
    expect(screen.getByLabelText(/^Label/)).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByTestId("form-errors")).toBeNull();
  });

  it("keeps what the user typed when it reloads, and takes the other change for what they did not touch", async () => {
    await openEdit();
    refuseWrite(new ApiError(409, JSON.stringify(STALE)));
    setField(/^Label/, "Ahmed (edited here)");
    setField("grade", "5");
    save(/save entity/i);
    await screen.findByTestId("stale-record");

    answerEntity(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));

    // Touched here: kept exactly as typed, even though the other client
    // wrote different values for both.
    await waitFor(() =>
      expect((screen.getByLabelText(/^Label/) as HTMLInputElement).value).toBe("Ahmed (edited here)")
    );
    expect((screen.getByLabelText("grade") as HTMLInputElement).value).toBe("5");
    // Not touched here: the other client's value arrives, which is the
    // whole point -- the next save no longer reverts it.
    expect((screen.getByLabelText("note") as HTMLInputElement).value).toBe("written by the other client");
    expect(screen.queryByTestId("stale-record")).toBeNull();
  });

  it("names what the reload brought in, so the other change is not invisible either", async () => {
    await openEdit();
    refuseWrite(new ApiError(409, JSON.stringify(STALE)));
    save(/save entity/i);
    await screen.findByTestId("stale-record");

    answerEntity(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/keeping your edits/i));
    expect(screen.getByRole("status").textContent).toContain("note");
  });

  it("saves against the reloaded timestamp afterwards, and still sends the whole attribute set", async () => {
    await openEdit();
    refuseWrite(new ApiError(409, JSON.stringify(STALE)));
    setField(/^Label/, "Ahmed (edited here)");
    save(/save entity/i);
    await screen.findByTestId("stale-record");

    answerEntity(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));
    await waitFor(() =>
      expect((screen.getByLabelText("note") as HTMLInputElement).value).toBe("written by the other client")
    );

    answerWrite(CHANGED);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(2));
    const retry = writes()[1].body;
    expect(retry.updated_at).toBe(CHANGED.updated_at);
    expect(retry.label).toBe("Ahmed (edited here)");
    expect(retry.attrs.note).toBe("written by the other client");
    // `grade` was never touched here, so the reload brought the other
    // client's 9 in and the retry carries it -- the reversion the whole
    // ruling is about, not happening.
    expect(retry.attrs.grade).toBe(9);
    // Tasks 11/12 are untouched: the payload is still the whole set, and
    // the stale key is still dropped.
    expect(retry.attrs).not.toHaveProperty("retired");
  });

  it("does not resurrect an attribute whose definition was deleted while the form was open", async () => {
    await openEdit();
    refuseWrite(new ApiError(409, JSON.stringify(STALE)));
    save(/save entity/i);
    await screen.findByTestId("stale-record");

    answerEntity(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));
    await waitFor(() => expect(screen.queryByTestId("stale-record")).toBeNull());
    answerWrite(CHANGED);
    save(/save entity/i);
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1].body.attrs).not.toHaveProperty("retired");
  });

  it("still marks the key field for the OTHER 409 a save can get", async () => {
    await openEdit();
    refuseWrite(
      new ApiError(409, JSON.stringify({ detail: "a entity row with the same type_id already exists" }))
    );
    save(/save entity/i);
    await waitFor(() => expect(screen.getByLabelText(/^Key/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.queryByTestId("stale-record")).toBeNull();
  });
});

/**
 * The Relationships section.
 *
 * An entity's page never showed which unit they work in, or which unit a
 * unit sits under -- while the delete warning at the bottom of the same
 * page counted exactly those rows. The section is here, rather than only
 * on `/relationships`, because "who works where" is a fact ABOUT this
 * entity and the page that describes the entity is where a reader looks
 * for it.
 */
describe("EntityRecord: the entity's relationships", () => {
  async function openEdit() {
    reads("/entities/42");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
  }

  it("lists a relationship this entity is the From end of, naming the other entity and the type", async () => {
    await openEdit();
    const row = await screen.findByTestId("relationship-301");
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("Ahmed");
    expect(cells[0]).toHaveTextContent(/this entity/i);
    expect(cells[1]).toHaveTextContent("works_in");
    expect(cells[2]).toHaveTextContent("North Depot");
    expect(within(cells[2]).getByRole("link", { name: "North Depot" })).toHaveAttribute("href", "/entities/71");
  });

  it("asks both directions, because the API has no 'either end' filter", async () => {
    await openEdit();
    await screen.findByTestId("relationship-301");
    const paths = requests().map((r) => r.path);
    expect(paths.some((p) => p.includes("from_entity_id=42"))).toBe(true);
    expect(paths.some((p) => p.includes("to_entity_id=42"))).toBe(true);
  });

  it("lists a relationship this entity is the TO end of, the other way round in the same table", async () => {
    // One table for both directions: an incoming row is the same edge seen
    // from the other end, and the sentence already says which end this
    // entity is on. A section that only asked `from_entity_id=` would
    // silently show half the model.
    await openEdit();
    const row = await screen.findByTestId("relationship-302");
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("South Depot");
    expect(cells[1]).toHaveTextContent("manages");
    expect(cells[2]).toHaveTextContent("Ahmed");
    expect(cells[2]).toHaveTextContent(/this entity/i);
    expect(cells[0]).not.toHaveTextContent(/this entity/i);
  });

  it("offers the connections this entity's TYPE can take part in, and only those", async () => {
    await openEdit();
    await screen.findByTestId("relationship-type-select");
    const options = within(screen.getByTestId("relationship-type-select"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    // employee is the From end of works_in and the To end of manages, so
    // the two sentences read in opposite directions.
    expect(options).toEqual(["Ahmed works_in a unit", "a unit manages Ahmed"]);
  });

  it("offers only entities of the far end's type, and never this entity itself", async () => {
    await openEdit();
    await waitFor(() =>
      expect(within(screen.getByTestId("relationship-other-select")).getAllByRole("option").length).toBeGreaterThan(1)
    );
    const options = within(screen.getByTestId("relationship-other-select"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(expect.arrayContaining(["North Depot", "South Depot"]));
    expect(options).not.toEqual(expect.arrayContaining(["Ahmed"]));
  });

  it("creates the relationship with this entity on the end its option names", async () => {
    await openEdit();
    await waitFor(() =>
      expect(within(screen.getByTestId("relationship-other-select")).getAllByRole("option").length).toBeGreaterThan(1)
    );
    answerWrite({ id: 302, relationship_type_id: 3, from_entity_id: 42, to_entity_id: 72, attrs: {} });
    fireEvent.change(screen.getByTestId("relationship-other-select"), { target: { value: "72" } });
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/relationships",
      body: { relationship_type_id: 3, from_entity_id: 42, to_entity_id: 72 },
    });
  });

  it("refuses to add one with no other end chosen, without sending anything", async () => {
    await openEdit();
    await screen.findByTestId("relationship-other-select");
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(writes()).toHaveLength(0);
    expect(screen.getByTestId("form-errors")).toHaveTextContent(/choose the unit to connect/i);
  });

  it("deletes a relationship after a confirmation naming the type and both ends", async () => {
    const confirm = vi.fn(() => true);
    window.confirm = confirm;
    await openEdit();
    await screen.findByTestId("relationship-301");
    answerWrite(undefined);

    fireEvent.click(within(screen.getByTestId("relationship-301")).getByRole("button", { name: /^Delete/ }));

    const message = (confirm.mock.calls[0] as unknown as [string])[0];
    expect(message).toContain("works_in");
    expect(message).toContain("Ahmed");
    expect(message).toContain("North Depot");
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toMatchObject({ method: "DELETE", path: "/api/v1/relationships/301" });
  });

  it("says so when the entity is connected to nothing, rather than showing an empty table", async () => {
    mockFetch.mockImplementation((p: string) => {
      if (p === "/api/v1/entity-types/5") return Promise.resolve(TYPE);
      if (p === "/api/v1/entities/42") return Promise.resolve(ENTITY);
      if (p === "/api/v1/entities/42/trees") return Promise.resolve({ entity_id: 42, trees: [] });
      if (p.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
      if (p.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: REL_TYPES, total: 1 });
      if (p.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 0 });
      if (p.startsWith("/api/v1/entities")) return Promise.resolve({ items: UNITS, total: 2 });
      return Promise.reject(new Error(`unexpected ${p}`));
    });
    renderAt("/entities/42");
    expect(await screen.findByTestId("relationships-empty")).toHaveTextContent(/not connected to anything yet/i);
  });

  it("says so when no relationship type can reach this entity's type at all", async () => {
    mockFetch.mockImplementation((p: string) => {
      if (p === "/api/v1/entity-types/5") return Promise.resolve(TYPE);
      if (p === "/api/v1/entities/42") return Promise.resolve(ENTITY);
      if (p === "/api/v1/entities/42/trees") return Promise.resolve({ entity_id: 42, trees: [] });
      if (p.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
      if (p.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: [], total: 0 });
      if (p.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 0 });
      if (p.startsWith("/api/v1/entities")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected ${p}`));
    });
    renderAt("/entities/42");
    expect(await screen.findByText(/No relationship type joins employee to anything yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /define one on the relationship types page/i })).toHaveAttribute(
      "href",
      "/relationship-types"
    );
  });

  it("is not offered on a new entity, which has no id to connect anything to", async () => {
    reads("/entities/new?type=5");
    expect(await screen.findByLabelText("grade")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Relationships" })).not.toBeInTheDocument();
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

  it("routes a refused loop through a reference to that reference's control", () => {
    const result = entityServerErrors(
      err(422, { detail: [{ loc: ["body", "grade"], msg: 'grade: "boss" would make a loop', kind: "cycle" }] }),
      names
    );
    expect(result.fields).toStrictEqual({ [attrField("grade")]: 'grade: "boss" would make a loop' });
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

/**
 * A kind nested in itself: Ahmed's `manager` names another employee. The page shows the chain
 * above and the tree below, and the manager field will not take Ahmed or anyone under him.
 */
describe("EntityRecord: a record nested in its own kind", () => {
  const MANAGER = { id: 18, entity_type_id: 5, name: "manager", data_type: "reference", required: false, unit: null,
    enum_values: null, default_value: null, target_type_id: 5 };
  const STAFF = [
    { ...ENTITY, id: 40, key: "sara", label: "Sara", attrs: {} },
    { ...ENTITY, id: 43, key: "omar", label: "Omar", attrs: {} },
  ];
  const TREE = {
    relationship_type_id: 8, name: "employee_manager", is_hierarchy: false, via_attribute: "manager",
    ancestors: [{ id: 40, key: "sara", label: "Sara", entity_type_id: 5, depth: 1 }],
    descendants: [{ id: 43, key: "omar", label: "Omar", entity_type_id: 5, depth: 1, parent_id: 42 }],
    loop: false, truncated: false, blocked: ["ahmed", "omar"],
  };

  function serve(tree: object, relTypes: object[] = []) {
    mockFetch.mockImplementation((p: string) => {
      if (p === "/api/v1/entity-types/5") return Promise.resolve({ ...TYPE, attributes: [...TYPE.attributes, MANAGER] });
      if (p === "/api/v1/entities/42") return Promise.resolve({ ...ENTITY, attrs: { ...ENTITY.attrs, manager: "sara" } });
      if (p === "/api/v1/entities/42/trees") return Promise.resolve({ entity_id: 42, trees: [tree] });
      if (p.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
      if (p.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: relTypes, total: relTypes.length });
      if (p.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 0 });
      if (p.startsWith("/api/v1/entities")) return Promise.resolve({ items: [...STAFF, ENTITY], total: 3 });
      return Promise.reject(new Error(`unexpected ${p}`));
    });
  }

  it("shows the chain above and the records below", async () => {
    serve(TREE);
    renderAt("/entities/42");
    const tree = await screen.findByTestId("tree-employee_manager");
    expect(within(tree).getByRole("navigation", { name: "Above in employee_manager" })).toHaveTextContent("Sara (sara)›Ahmed (ahmed)");
    expect(within(tree).getByRole("link", { name: "Omar (omar)" })).toHaveAttribute("href", "/entities/43");
    expect(within(tree).queryByRole("alert")).toBeNull();
  });

  it("greys out the record itself and those below it as its manager", async () => {
    serve(TREE);
    renderAt("/entities/42");
    await screen.findByTestId("tree-employee_manager");
    fireEvent.focus(screen.getByTestId("attr-manager"));
    expect(await screen.findByRole("option", { name: /omar — Omar \(below this one: a loop\)/ })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("option", { name: /ahmed — Ahmed \(this record\)/ })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("option", { name: "sara — Sara" })).not.toHaveAttribute("aria-disabled");
  });

  it("warns when the chain already loops", async () => {
    serve({ ...TREE, loop: true });
    renderAt("/entities/42");
    const tree = await screen.findByTestId("tree-employee_manager");
    expect(within(tree).getByRole("alert")).toHaveTextContent(/comes back on itself/);
  });

  it("will not offer someone below as the parent in a hierarchy, nor someone above as the child", async () => {
    const MENTORS = { id: 9, domain_id: 7, name: "mentors", from_type_id: 5, to_type_id: 5, cardinality: "one_to_many",
      is_hierarchy: true, colour: null, updated_at: "t" };
    serve({ ...TREE, relationship_type_id: 9, name: "mentors", is_hierarchy: true, via_attribute: null }, [MENTORS]);
    renderAt("/entities/42");
    const kind = await screen.findByTestId("relationship-type-select");
    fireEvent.change(kind, { target: { value: "9:to" } });
    const other = () => within(screen.getByTestId("relationship-other-select"));
    await waitFor(() => expect(other().getByRole("option", { name: /Omar.*below it: a loop/ })).toBeDisabled());
    expect(other().getByRole("option", { name: /Sara/ })).not.toBeDisabled();
    fireEvent.change(kind, { target: { value: "9:from" } });
    await waitFor(() => expect(other().getByRole("option", { name: /Sara.*above it: a loop/ })).toBeDisabled());
    expect(other().getByRole("option", { name: /Omar/ })).not.toBeDisabled();
  });
});

describe("EntityRecord: records that name this one", () => {
  const field = (attribute: string, required: boolean, keys: string[], count = keys.length) => ({
    kind: "shift", attribute, required, count, records: keys.map((key, i) => ({ id: 500 + i, key, label: null })),
  });

  it("refuses to delete while a required reference names it, and says which records", async () => {
    referrersAnswer = { entity_id: 42, fields: [field("lead", true, ["mon-am"], 3)], blocks_delete: true };
    reads("/entities/42");
    const refused = await screen.findByTestId("delete-refused");
    expect(refused).toHaveTextContent("shift.lead — mon-am and 2 more");
    expect(within(refused).getByRole("link", { name: "mon-am" })).toHaveAttribute("href", "/entities/500");
    expect(screen.getByRole("button", { name: "Delete entity" })).toBeDisabled();
  });

  it("says which fields a delete empties, in the page and in the question", async () => {
    referrersAnswer = { entity_id: 42, fields: [field("cover", false, ["tue-pm", "wed-pm"])], blocks_delete: false };
    reads("/entities/42");
    expect(await screen.findByTestId("delete-clears")).toHaveTextContent("shift.cover — tue-pm, wed-pm");
    window.confirm = vi.fn(() => false);
    fireEvent.click(screen.getByRole("button", { name: "Delete entity" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("It also empties shift.cover on 2 records."));
  });
});
