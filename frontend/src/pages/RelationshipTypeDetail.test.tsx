import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RelationshipTypeDetail from "./RelationshipTypeDetail";
import { ToastProvider } from "../components/ToastProvider";
import type { RelationshipType } from "../api/v1";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const ENTITY_TYPES = [
  { id: 5, domain_id: 7, name: "employee", role: "agent", colour: "#1f77b4", attributes: [] },
  { id: 9, domain_id: 7, name: "shift", role: "time", colour: null, attributes: [] },
];

/** An ordinary type whose ends differ and whose cardinality is neither the
 * column default nor the hierarchy value. */
const TYPE: RelationshipType = {
  id: 21,
  domain_id: 7,
  name: "works_on",
  from_type_id: 5,
  to_type_id: 9,
  cardinality: "many_to_one",
  is_hierarchy: false,
  colour: "#2ca02c",
  updated_at: "2026-09-20T09:00:00+00:00",
};

type Handler = (path: string, init?: RequestInit) => Promise<unknown> | undefined;

function serve(write: Handler = () => undefined, type: RelationshipType = TYPE, relationshipTotal = 3) {
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      const answer = write(path, init);
      if (answer) return answer;
      return Promise.reject(new Error(`unexpected ${method} ${path}`));
    }
    if (path === "/api/v1/relationship-types/21") return Promise.resolve(type);
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
    if (path.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: relationshipTotal });
    return Promise.reject(new ApiError(404, JSON.stringify({ detail: "relationship type not found" })));
  });
}

function writes(): { method: string; path: string; body: Record<string, unknown> | undefined }[] {
  return mockFetch.mock.calls
    .filter((call) => (call[1] as RequestInit | undefined)?.method && (call[1] as RequestInit).method !== "GET")
    .map((call) => {
      const init = call[1] as RequestInit;
      return {
        method: init.method as string,
        path: call[0] as string,
        body: init.body ? JSON.parse(init.body as string) : undefined,
      };
    });
}

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(path = "/relationship-types/21") {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/relationship-types" element={<p>list page</p>} />
            <Route path="/relationship-types/:id" element={<RelationshipTypeDetail />} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const save = () => screen.getByRole("button", { name: "Save relationship type" });

describe("RelationshipTypeDetail", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the stored row in the form, not defaults", async () => {
    serve();
    renderPage();
    await screen.findByDisplayValue("works_on");
    expect((screen.getByLabelText(/^From entity type/) as HTMLSelectElement).value).toBe("5");
    expect((screen.getByLabelText(/^To entity type/) as HTMLSelectElement).value).toBe("9");
    expect((screen.getByLabelText(/^Cardinality/) as HTMLSelectElement).value).toBe("many_to_one");
    expect(screen.getByRole("checkbox", { name: /hierarchy/i })).not.toBeChecked();
  });

  it("opens a stored hierarchy type already locked and explained", async () => {
    serve(() => undefined, {
      ...TYPE,
      id: 21,
      name: "reports_to",
      from_type_id: 5,
      to_type_id: 5,
      cardinality: "one_to_many",
      is_hierarchy: true,
    });
    renderPage();
    await screen.findByDisplayValue("reports_to");
    expect(screen.getByRole("checkbox", { name: /hierarchy/i })).toBeChecked();
    expect(screen.getByLabelText(/^To entity type/)).toBeDisabled();
    expect(screen.getByLabelText(/^Cardinality/)).toBeDisabled();
    expect(screen.getByTestId("hierarchy-constraint")).toBeInTheDocument();
  });

  it("renames with a PATCH and confirms with a toast", async () => {
    serve((path, init) =>
      init?.method === "PATCH" && path === "/api/v1/relationship-types/21"
        ? Promise.resolve({ ...TYPE, name: "assigned_to" })
        : undefined
    );
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "assigned_to" } });
    fireEvent.click(save());

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/relationship type saved/i));
    expect(writes()).toEqual([
      {
        method: "PATCH",
        path: "/api/v1/relationship-types/21",
        body: {
          name: "assigned_to",
          from_type_id: 5,
          to_type_id: 9,
          cardinality: "many_to_one",
          is_hierarchy: false,
          colour: "#2ca02c",
          // Ruling 42 -- see EntityTypeDetail.test.tsx.
          updated_at: "2026-09-20T09:00:00+00:00",
        },
      },
    ]);
  });

  it("clears the colour back to automatic", async () => {
    serve((_path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, colour: null }) : undefined));
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "" } });
    fireEvent.click(save());

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ colour: null });
  });

  it("sets a colour, normalised to lower case", async () => {
    serve((_path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, colour: "#b8860b" }) : undefined));
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#B8860B" } });
    fireEvent.click(save());

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ colour: "#b8860b" });
  });

  it("refuses a malformed hex without sending anything, and says so in the summary", async () => {
    serve();
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "banana" } });
    fireEvent.click(save());
    await flush();

    expect(writes()).toHaveLength(0);
    expect(screen.getByTestId("form-errors")).toHaveTextContent(/Colour: Use a six-digit hex colour/i);
    expect(screen.queryByText("Relationship type saved")).not.toBeInTheDocument();
  });

  it("turning a stored type into a hierarchy sends a row the CHECK accepts", async () => {
    serve((_path, init) => (init?.method === "PATCH" ? Promise.resolve({ ...TYPE, is_hierarchy: true }) : undefined));
    renderPage();
    await screen.findByDisplayValue("works_on");
    // Starts invalid-for-a-hierarchy on both counts: ends 5 vs 9, many_to_one.
    expect((screen.getByLabelText(/^To entity type/) as HTMLSelectElement).value).toBe("9");

    fireEvent.click(screen.getByRole("checkbox", { name: /hierarchy/i }));
    fireEvent.click(save());

    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({
      from_type_id: 5,
      to_type_id: 5,
      cardinality: "one_to_many",
      is_hierarchy: true,
    });
  });

  it("refuses a bad name before sending", async () => {
    serve();
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "1bad" } });
    fireEvent.click(save());
    await flush();

    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true");
    expect(writes()).toEqual([]);
  });

  it("marks the name field on a duplicate-name 409", async () => {
    serve((_path, init) =>
      init?.method === "PATCH"
        ? Promise.reject(
            new ApiError(
              409,
              JSON.stringify({ detail: "a relationship_type row with the same domain_id_name already exists" })
            )
          )
        : undefined
    );
    renderPage();
    await screen.findByDisplayValue("works_on");

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "reports_to" } });
    fireEvent.click(save());

    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByLabelText(/^Name/)).toHaveAccessibleDescription(
      /already has a relationship type with this name/i
    );
  });

  it("says the type is not there when the API 404s", async () => {
    serve();
    renderPage("/relationship-types/999");
    expect(await screen.findByText(/relationship type not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to relationship types/i })).toBeInTheDocument();
    // Same page, no level-1 heading: an axe `page-has-heading-one`
    // violation, and nothing for a screen-reader user to land on.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/relationship type not found/i);
  });

  describe("deleting", () => {
    it("names the relationships that go with it, and does nothing on cancel", async () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      serve();
      renderPage();
      await screen.findByDisplayValue("works_on");
      // The count comes from a list call; wait for it before reading the text.
      await screen.findByText(/3 relationships/i);

      fireEvent.click(screen.getByRole("button", { name: "Delete relationship type" }));
      await flush();

      const text = confirm.mock.calls[0][0] as string;
      expect(text).toMatch(/works_on/);
      expect(text).toMatch(/3 relationships/i);
      expect(text).toMatch(/cannot be undone/i);
      expect(writes()).toEqual([]);
      expect(screen.getByTestId("location")).toHaveTextContent("/relationship-types/21");
    });

    it("says '1 relationship', not '1 relationships'", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(false);
      serve(() => undefined, TYPE, 1);
      renderPage();
      await screen.findByText(/1 relationship\b/i);
      fireEvent.click(screen.getByRole("button", { name: "Delete relationship type" }));
      expect((window.confirm as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatch(/\b1 relationship\b/);
    });

    it("deletes on confirm, toasts, and returns to the list", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      serve((path, init) =>
        init?.method === "DELETE" && path === "/api/v1/relationship-types/21" ? Promise.resolve(null) : undefined
      );
      renderPage();
      await screen.findByDisplayValue("works_on");

      fireEvent.click(screen.getByRole("button", { name: "Delete relationship type" }));

      await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/relationship-types$/));
      expect(writes().map((w) => `${w.method} ${w.path}`)).toEqual(["DELETE /api/v1/relationship-types/21"]);
    });
  });
});

describe("RelationshipTypeDetail: a concurrent edit (Ruling 42)", () => {
  const STALE = new ApiError(409, JSON.stringify({ detail: "This relationship type was changed by someone else after this form loaded it. Reload the relationship type and apply your changes to the current version." }));
  const CHANGED: RelationshipType = {
    ...TYPE,
    cardinality: "one_to_many",
    updated_at: "2026-09-20T09:05:00+00:00",
  };

  function answerGetsWith(type: RelationshipType) {
    mockFetch.mockImplementation((path: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") !== "GET") return Promise.reject(STALE);
      if (path === "/api/v1/relationship-types/21") return Promise.resolve(type);
      if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
      if (path.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 3 });
      return Promise.reject(new ApiError(404, JSON.stringify({ detail: "relationship type not found" })));
    });
  }

  it("refuses with a reload offer, then keeps the typed name and takes the other cardinality", async () => {
    answerGetsWith(TYPE);
    renderPage();
    await screen.findByDisplayValue("works_on");
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "assigned_to" } });
    fireEvent.click(save());

    const notice = await screen.findByTestId("stale-record");
    expect(notice).toHaveAttribute("role", "alert");

    answerGetsWith(CHANGED);
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));

    await waitFor(() => expect(screen.getByLabelText(/^Cardinality/)).toHaveValue("one_to_many"));
    expect(screen.getByLabelText(/^Name/)).toHaveValue("assigned_to");
    expect(screen.queryByTestId("stale-record")).toBeNull();
  });
});
