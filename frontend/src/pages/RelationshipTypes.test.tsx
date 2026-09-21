import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RelationshipTypes from "./RelationshipTypes";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { typeColour } from "../lib/colour";
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

// One ordinary edge between two different types and one self-referencing
// hierarchy, so a page that reads the wrong end -- or shows a constant --
// is caught. `works_on` sorts before... no: the API orders by name, and
// "reports_to" < "works_on", which is the order these are listed in.
const REL_TYPES = [
  {
    id: 22,
    domain_id: 7,
    name: "reports_to",
    from_type_id: 5,
    to_type_id: 5,
    cardinality: "one_to_many",
    is_hierarchy: true,
    colour: null,
  },
  {
    id: 21,
    domain_id: 7,
    name: "works_on",
    from_type_id: 5,
    to_type_id: 9,
    cardinality: "many_to_many",
    is_hierarchy: false,
    colour: "#2ca02c",
  },
];

function serve(overrides: (path: string, init?: RequestInit) => unknown | undefined = () => undefined) {
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    const override = overrides(path, init);
    if (override !== undefined) return override;
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
    if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: REL_TYPES, total: 2 });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage() {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/relationship-types"]}>
          <Routes>
            <Route path="/relationship-types" element={<RelationshipTypes />} />
            <Route path="/relationship-types/:id" element={<p>detail page</p>} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function posted(): { path: string; body: Record<string, unknown> } | null {
  const call = mockFetch.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "POST");
  if (!call) return null;
  return { path: call[0] as string, body: JSON.parse((call[1] as RequestInit).body as string) };
}

const nameBox = () => screen.getByLabelText(/^Name/);
const hierarchyBox = () => screen.getByRole("checkbox", { name: /hierarchy/i });

describe("RelationshipTypes list page", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
  });

  it("with no domain selected, points at the selector and does not query", async () => {
    mockFetch.mockRejectedValue(new Error("should not be called"));
    renderPage();
    expect(await screen.findByText(/choose a domain in the sidebar/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(mockFetch.mock.calls).toHaveLength(0);
  });

  it("lists the domain's relationship types with both ends, cardinality and hierarchy", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();

    const reportsTo = await screen.findByRole("link", { name: "reports_to" });
    expect(reportsTo).toHaveAttribute("href", "/relationship-types/22");
    expect(screen.getByRole("link", { name: "works_on" })).toHaveAttribute("href", "/relationship-types/21");

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    // The ends are the entity types' NAMES, resolved from their ids.
    // reports_to is a hierarchy, so "employee" is on BOTH of its ends.
    expect(within(rows[0]).getAllByText("employee")).toHaveLength(2);
    expect(within(rows[0]).getByText("Yes")).toBeInTheDocument();
    // By POSITION, not merely by presence: works_on runs employee -> shift,
    // and a page that swapped the two columns would still show both names.
    // The name is a <th scope="row">, so the cells start at From.
    const cells = within(rows[1]).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("employee");
    expect(cells[1]).toHaveTextContent("shift");
    expect(within(rows[1]).getByText("No")).toBeInTheDocument();
    // Different cardinalities, so a constant would fail.
    expect(within(rows[0]).getByText(/1 → n/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/n → n/)).toBeInTheDocument();

    const listed = mockFetch.mock.calls.map((c) => c[0] as string);
    expect(listed.some((p) => p.startsWith("/api/v1/relationship-types") && p.includes("domain_id=7"))).toBe(true);
  });

  it("shows each type's colour, and says which are automatic", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    expect(screen.getByTestId("reltype-swatch-works_on")).toHaveStyle({ backgroundColor: "#2ca02c" });
    expect(screen.getByTestId("reltype-swatch-reports_to")).toHaveStyle({
      backgroundColor: typeColour({ id: "22", colour: null }),
    });
    expect(screen.getByText("#2ca02c")).toBeInTheDocument();
    expect(screen.getByText("automatic")).toBeInTheDocument();
  });

  it("says so when the domain has no relationship types yet", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((path) => (path.startsWith("/api/v1/relationship-types") ? Promise.resolve({ items: [], total: 0 }) : undefined));
    renderPage();
    expect(await screen.findByText(/no relationship types in this domain yet/i)).toBeInTheDocument();
  });

  it("shows a load failure with a retry", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    let fail = true;
    serve((path) =>
      fail && path.startsWith("/api/v1/relationship-types") ? Promise.reject(new ApiError(500, "boom")) : undefined
    );
    renderPage();
    expect(await screen.findByText(/server error \(500\)/i)).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "works_on" })).toBeInTheDocument();
  });

  it("cannot be used until the domain has entity types to join", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((path) => (path.startsWith("/api/v1/entity-types") ? Promise.resolve({ items: [], total: 0 }) : undefined));
    renderPage();
    expect(await screen.findByText(/needs at least one entity type/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create relationship type" })).not.toBeInTheDocument();
  });

  it("creates an ordinary type with the ends and cardinality chosen, and opens it", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((_path, init) =>
      init?.method === "POST"
        ? Promise.resolve({ id: 44, domain_id: 7, name: "staffs", from_type_id: 9, to_type_id: 5 })
        : undefined
    );
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "staffs" } });
    fireEvent.change(screen.getByLabelText(/^From entity type/), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText(/^To entity type/), { target: { value: "5" } });
    // Not the default, and not the hierarchy value either: a form that
    // ignored the select would still pass a default-only assertion.
    fireEvent.change(screen.getByLabelText(/^Cardinality/), { target: { value: "many_to_one" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/relationship-types/44"));
    expect(posted()?.path).toBe("/api/v1/relationship-types");
    expect(posted()?.body).toEqual({
      domain_id: 7,
      name: "staffs",
      from_type_id: 9,
      to_type_id: 5,
      cardinality: "many_to_one",
      is_hierarchy: false,
      colour: null,
    });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/relationship type "staffs" created/i));
  });

  it("creates a hierarchy type that the database cannot refuse", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((_path, init) => (init?.method === "POST" ? Promise.resolve({ id: 45, name: "manages" }) : undefined));
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "manages" } });
    // Deliberately set the two ends apart FIRST, then tick the box: the
    // payload below is only evidence of a constraint if the form had an
    // invalid combination in hand at the moment the box was ticked.
    fireEvent.change(screen.getByLabelText(/^From entity type/), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText(/^To entity type/), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/^Cardinality/), { target: { value: "many_to_many" } });
    fireEvent.click(hierarchyBox());
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() => expect(posted()).not.toBeNull());
    expect(posted()?.body).toEqual({
      domain_id: 7,
      name: "manages",
      from_type_id: 9,
      to_type_id: 9,
      cardinality: "one_to_many",
      is_hierarchy: true,
      colour: null,
    });
  });

  it("creates with the colour chosen on the form", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((_path, init) => (init?.method === "POST" ? Promise.resolve({ id: 46, name: "uses" }) : undefined));
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "uses" } });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#B8860B" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() => expect(posted()).not.toBeNull());
    expect(posted()?.body).toMatchObject({ colour: "#b8860b" });
  });

  it("refuses a name the server would reject, before sending", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "Works On" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    expect(nameBox()).toHaveAttribute("aria-invalid", "true");
    expect(posted()).toBeNull();
  });

  it("marks the name field on a duplicate-name 409, not the ends", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((_path, init) =>
      init?.method === "POST"
        ? Promise.reject(
            // The 409's *string* detail, which is what this constraint
            // actually returns -- a 422 list would take a different branch.
            new ApiError(
              409,
              JSON.stringify({ detail: "a relationship_type row with the same domain_id_name already exists" })
            )
          )
        : undefined
    );
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "works_on" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() => expect(nameBox()).toHaveAttribute("aria-invalid", "true"));
    expect(nameBox()).toHaveAccessibleDescription(/already has a relationship type with this name/i);
    expect(screen.getByLabelText(/^From entity type/)).not.toHaveAttribute("aria-invalid");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/relationship-types$/);
  });

  it("marks the cardinality field when a 422 names it", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve((_path, init) =>
      init?.method === "POST"
        ? Promise.reject(
            new ApiError(
              422,
              JSON.stringify({
                detail: [{ loc: ["body", "cardinality"], msg: "a hierarchy must be one_to_many", type: "value_error" }],
              })
            )
          )
        : undefined
    );
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "manages" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() => expect(screen.getByLabelText(/^Cardinality/)).toHaveAttribute("aria-invalid", "true"));
    expect(nameBox()).not.toHaveAttribute("aria-invalid");
  });
  it("refuses to create a type whose colour box holds junk, and says so in the summary", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await screen.findByRole("link", { name: "works_on" });

    fireEvent.change(nameBox(), { target: { value: "supplies" } });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "banana" } });
    fireEvent.click(screen.getByRole("button", { name: "Create relationship type" }));

    await waitFor(() =>
      expect(screen.getByTestId("form-errors")).toHaveTextContent(/Colour: Use a six-digit hex colour/i)
    );
    expect(posted()).toBeNull();
  });
});
