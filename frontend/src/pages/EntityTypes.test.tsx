import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityTypes from "./EntityTypes";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { typeColour } from "../lib/colour";
import { EDITOR_ME, VIEWER_ME, editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

// Returned in the API's own order (by name). Roles deliberately differ from
// each other and from the "other" default, so a page that shows a constant
// or the wrong row's role is caught.
const TYPES = [
  {
    id: 5,
    domain_id: 7,
    name: "employee",
    role: "agent",
    colour: "#1f77b4",
    attributes: [
      { id: 11, entity_type_id: 5, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: 3 },
      { id: 12, entity_type_id: 5, name: "kind", data_type: "enum", required: false, unit: null, enum_values: ["a"], default_value: null },
    ],
  },
  // No colour: the list has to show both a chosen colour and "automatic".
  { id: 9, domain_id: 7, name: "shift", role: "time", colour: null, attributes: [] },
];

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(me: typeof EDITOR_ME | typeof VIEWER_ME = EDITOR_ME) {
  const queryClient = editorQueryClient(me);
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/entity-types"]}>
          <Routes>
            <Route path="/entity-types" element={<EntityTypes />} />
            <Route path="/entity-types/:id" element={<p>detail page</p>} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function listCalls(): string[] {
  return mockFetch.mock.calls.map((call) => call[0] as string).filter((p) => p.startsWith("/api/v1/entity-types"));
}

describe("EntityTypes list page", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
  });

  it("with no domain selected, points at the selector and does not query", async () => {
    mockFetch.mockRejectedValue(new Error("should not be called"));
    renderPage();
    expect(await screen.findByText(/choose a domain in the sidebar/i)).toBeInTheDocument();
    // Not an error: nothing red, no retry (the toast region's empty role="alert" is always mounted).
    expect(screen.queryByText(/error|failed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Retry/ })).not.toBeInTheDocument();
    expect(listCalls()).toEqual([]);
  });

  it("lists the selected domain's types with their role and attribute count", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockResolvedValue({ items: TYPES, total: 2 });
    renderPage();

    const employee = await screen.findByRole("link", { name: "employee" });
    expect(employee).toHaveAttribute("href", "/entity-types/5");
    expect(screen.getByRole("link", { name: "shift" })).toHaveAttribute("href", "/entity-types/9");

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Agent")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Time")).toBeInTheDocument();
    expect(within(rows[1]).getByText("0")).toBeInTheDocument();

    expect(listCalls()[0]).toContain("domain_id=7");
  });

  it("says so when the domain has no types yet", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText(/no record types in this domain yet/i)).toBeInTheDocument();
  });

  it("shows a load failure with a retry", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderPage();
    expect(await screen.findByText(/server error \(500\)/i)).toBeInTheDocument();
    mockFetch.mockResolvedValue({ items: TYPES, total: 2 });
    fireEvent.click(screen.getByRole("button", { name: /^Retry/ }));
    expect(await screen.findByRole("link", { name: "employee" })).toBeInTheDocument();
  });

  it("creates a type in the selected domain, confirms with a toast and opens it", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({ id: 44, domain_id: 7, name: "unit", role: "org", attributes: [] });
      }
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "unit" } });
    fireEvent.change(screen.getByLabelText(/^Role/), { target: { value: "org" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/entity-types/44"));
    const post = mockFetch.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/entity-types");
    expect(JSON.parse(post?.[1].body as string)).toEqual({ domain_id: 7, name: "unit", role: "org", colour: null });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/record type "unit" created/i));
  });

  it("refuses a name the server would reject, before sending", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockResolvedValue({ items: TYPES, total: 2 });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "Employee" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true");
    expect(mockFetch.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("marks the name field on a duplicate-name 409, not the role", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.reject(
          new ApiError(409, JSON.stringify({ detail: "a entity_type row with the same domain_id_name already exists" }))
        );
      }
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "employee" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByLabelText(/^Name/)).toHaveAccessibleDescription(/already has a record type with this name/i);
    expect(screen.getByLabelText(/^Role/)).not.toHaveAttribute("aria-invalid");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/entity-types$/);
  });

  it("marks the role field when a 422 names role", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.reject(
          new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "role"], msg: "Input should be 'agent'", type: "literal_error" }] }))
        );
      }
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "unit" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() => expect(screen.getByLabelText(/^Role/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByLabelText(/^Name/)).not.toHaveAttribute("aria-invalid");
  });

  // --- Task 14b: colour --------------------------------------------------

  it("shows each type's colour, and says which are automatic", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockResolvedValue({ items: TYPES, total: 2 });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    // The swatch is decorative (aria-hidden); the text beside it is what a
    // screen reader -- or anyone who cannot tell two swatches apart --
    // actually reads.
    expect(screen.getByTestId("type-swatch-employee")).toHaveStyle({ backgroundColor: "#1f77b4" });
    expect(screen.getByTestId("type-swatch-shift")).toHaveStyle({
      backgroundColor: typeColour({ id: "9", colour: null }),
    });
    expect(screen.getByText("#1f77b4")).toBeInTheDocument();
    expect(screen.getByText("automatic")).toBeInTheDocument();
  });

  it("creates a type with the colour chosen on the form", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve({ id: 44, name: "unit" });
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "unit" } });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#B8860B" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() => {
      const post = mockFetch.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        domain_id: 7,
        name: "unit",
        role: "other",
        colour: "#b8860b",
      });
    });
  });
  it("shows a 422 the server raises on colour under the colour box", async () => {
    // The parents no longer render their own message beside ColourField --
    // the field draws whatever the form is showing -- so a server refusal
    // that names `colour` has to reach it, or it would appear nowhere.
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.reject(
          new ApiError(
            422,
            JSON.stringify({ detail: [{ loc: ["body", "colour"], msg: "colour must be #rrggbb" }] })
          )
        );
      }
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "unit" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() => expect(screen.getByTestId("form-errors")).toHaveTextContent(/colour must be #rrggbb/i));
    expect(screen.getByTestId("colour-hex")).toHaveAttribute("aria-invalid", "true");
    // Once in the summary, once under the control -- and nowhere else.
    expect(screen.getAllByText("colour must be #rrggbb")).toHaveLength(2);
  });

  it("refuses to create a type whose colour box holds junk, and says so in the summary", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.reject(new Error("should not be sent"));
      return Promise.resolve({ items: TYPES, total: 2 });
    });
    renderPage();
    await screen.findByRole("link", { name: "employee" });

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "unit" } });
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "banana" } });
    fireEvent.click(screen.getByRole("button", { name: "Create record type" }));

    await waitFor(() =>
      expect(screen.getByTestId("form-errors")).toHaveTextContent(/Colour: Use a six-digit hex colour/i)
    );
    expect(mockFetch.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("does not offer a way to create a type to an account that may not", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockResolvedValue({ items: TYPES, total: 2 });
    renderPage(VIEWER_ME);
    expect(await screen.findByRole("link", { name: "employee" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "New record type" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create record type" })).not.toBeInTheDocument();
  });
});
