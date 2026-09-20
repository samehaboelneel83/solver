import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Relationships from "./Relationships";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const ENTITY_TYPES = [
  { id: 1, domain_id: 7, name: "employee", role: "agent", colour: null, attributes: [], updated_at: "t" },
  { id: 2, domain_id: 7, name: "unit", role: "org", colour: null, attributes: [], updated_at: "t" },
];

/** employee -> unit, and unit -> unit as a hierarchy. Two types, so a page
 * that hard-wired one of them (or fetched only the first) is caught. */
const REL_TYPES = [
  {
    id: 5,
    domain_id: 7,
    name: "works_in",
    from_type_id: 1,
    to_type_id: 2,
    cardinality: "many_to_one",
    is_hierarchy: false,
    colour: null,
    updated_at: "t",
  },
  {
    id: 6,
    domain_id: 7,
    name: "reports_to",
    from_type_id: 2,
    to_type_id: 2,
    cardinality: "one_to_many",
    is_hierarchy: true,
    colour: null,
    updated_at: "t",
  },
];

const EMPLOYEES = [
  { id: 11, entity_type_id: 1, key: "ahmed", label: "Ahmed Salah", sort_order: 0, active: true, attrs: {}, updated_at: "t" },
  // No label: the picker and the table must fall back to the key rather
  // than render an empty cell.
  { id: 12, entity_type_id: 1, key: "bilal", label: null, sort_order: 1, active: true, attrs: {}, updated_at: "t" },
];
const UNITS = [
  { id: 21, entity_type_id: 2, key: "hq", label: "Head Office", sort_order: 0, active: true, attrs: {}, updated_at: "t" },
  { id: 22, entity_type_id: 2, key: "north", label: "North Depot", sort_order: 1, active: true, attrs: {}, updated_at: "t" },
];

const WORKS_IN_ROWS = [
  { id: 101, relationship_type_id: 5, from_entity_id: 11, to_entity_id: 22, attrs: {}, valid_from: null, valid_to: null },
];
const REPORTS_TO_ROWS = [
  { id: 102, relationship_type_id: 6, from_entity_id: 21, to_entity_id: 22, attrs: {}, valid_from: null, valid_to: null },
];

type Handler = (path: string, init?: RequestInit) => Promise<unknown> | undefined;

function serve(write: Handler = () => undefined, over: { relTypes?: unknown[] } = {}) {
  mockFetch.mockImplementation((path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      const answer = write(path, init);
      if (answer) return answer;
      return Promise.reject(new Error(`unexpected ${method} ${path}`));
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
    if (path.startsWith("/api/v1/relationship-types")) {
      return Promise.resolve({ items: over.relTypes ?? REL_TYPES, total: (over.relTypes ?? REL_TYPES).length });
    }
    if (path.startsWith("/api/v1/relationships")) {
      if (path.includes("relationship_type_id=5")) return Promise.resolve({ items: WORKS_IN_ROWS, total: 1 });
      if (path.includes("relationship_type_id=6")) return Promise.resolve({ items: REPORTS_TO_ROWS, total: 1 });
      return Promise.resolve({ items: [], total: 0 });
    }
    if (path.startsWith("/api/v1/entities")) {
      if (path.includes("entity_type_id=1")) return Promise.resolve({ items: EMPLOYEES, total: 2 });
      if (path.includes("entity_type_id=2")) return Promise.resolve({ items: UNITS, total: 2 });
      return Promise.resolve({ items: [], total: 0 });
    }
    return Promise.reject(new Error(`unexpected GET ${path}`));
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

function gets(): string[] {
  return mockFetch.mock.calls
    .filter((call) => !(call[1] as RequestInit | undefined)?.method || (call[1] as RequestInit).method === "GET")
    .map((call) => call[0] as string);
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/relationships"]}>
          <Routes>
            <Route path="/relationships" element={<Relationships />} />
            <Route path="/entities/:id" element={<p>entity page</p>} />
            <Route path="/relationship-types" element={<p>relationship types page</p>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const table = () => screen.getByRole("table", { name: "Relationships" });
const dataRows = () => within(table()).getAllByRole("row").slice(1);

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("Relationships page", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
    window.confirm = vi.fn(() => true);
  });

  it("with no domain selected, points at the selector and does not query", async () => {
    mockFetch.mockRejectedValue(new Error("should not be called"));
    renderPage();
    expect(await screen.findByText(/choose a domain in the sidebar/i)).toBeInTheDocument();
    expect(mockFetch.mock.calls).toHaveLength(0);
  });

  it("lists every relationship in the domain, naming both entities and the type", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();

    await waitFor(() => expect(dataRows()).toHaveLength(2));
    // By POSITION, so a page that swapped From and To -- or that showed
    // the ids it actually holds -- would fail.
    const worksIn = within(screen.getByTestId("relationship-101")).getAllByRole("cell");
    expect(worksIn[0]).toHaveTextContent("Ahmed Salah");
    expect(worksIn[1]).toHaveTextContent("works_in");
    expect(worksIn[2]).toHaveTextContent("North Depot");

    const reportsTo = within(screen.getByTestId("relationship-102")).getAllByRole("cell");
    expect(reportsTo[0]).toHaveTextContent("Head Office");
    expect(reportsTo[1]).toHaveTextContent("reports_to");
    expect(reportsTo[2]).toHaveTextContent("North Depot");
  });

  it("asks for one list per relationship type, since the API has no domain filter", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await waitFor(() => expect(dataRows()).toHaveLength(2));

    const relationshipGets = gets().filter((p) => p.startsWith("/api/v1/relationships"));
    expect(relationshipGets.some((p) => p.includes("relationship_type_id=5"))).toBe(true);
    expect(relationshipGets.some((p) => p.includes("relationship_type_id=6"))).toBe(true);
  });

  it("links each endpoint to its entity page, because a name is not much use on its own", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await waitFor(() => expect(dataRows()).toHaveLength(2));

    expect(screen.getByRole("link", { name: "Ahmed Salah" })).toHaveAttribute("href", "/entities/11");
    expect(screen.getAllByRole("link", { name: "North Depot" })[0]).toHaveAttribute("href", "/entities/22");
  });

  it("filters to one type, and stops asking for the others", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await waitFor(() => expect(dataRows()).toHaveLength(2));
    mockFetch.mockClear();

    fireEvent.change(screen.getByTestId("relationship-filter"), { target: { value: "5" } });

    await waitFor(() => expect(dataRows()).toHaveLength(1));
    expect(screen.getByTestId("relationship-101")).toBeInTheDocument();
    expect(screen.queryByTestId("relationship-102")).not.toBeInTheDocument();
  });

  it("says how many there are, so an empty domain is legibly empty rather than broken", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve();
    renderPage();
    await waitFor(() => expect(screen.getByTestId("relationship-count")).toHaveTextContent("2 relationships"));
  });

  it("says so when the domain has relationship types but no relationships", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    mockFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ items: ENTITY_TYPES, total: 2 });
      if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: REL_TYPES, total: 2 });
      if (path.startsWith("/api/v1/relationships")) return Promise.resolve({ items: [], total: 0 });
      if (path.startsWith("/api/v1/entities")) return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderPage();
    expect(await screen.findByTestId("relationships-empty")).toHaveTextContent(/no relationships in this domain yet/i);
  });

  it("sends the user to the relationship types page when the domain has no types at all", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    serve(() => undefined, { relTypes: [] });
    renderPage();
    expect(await screen.findByText(/a relationship is always of some type/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /define the first one/i })).toHaveAttribute("href", "/relationship-types");
  });

  describe("creating one", () => {
    async function ready() {
      localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
      renderPage();
      await waitFor(() => expect(screen.getByTestId("relationship-type-select")).toBeInTheDocument());
    }

    it("offers only entities of the type each end requires", async () => {
      serve();
      await ready();
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );

      // works_in is employee -> unit, so From offers employees and To units.
      const from = within(screen.getByTestId("relationship-from-select"))
        .getAllByRole("option")
        .map((o) => o.textContent);
      const to = within(screen.getByTestId("relationship-to-select"))
        .getAllByRole("option")
        .map((o) => o.textContent);
      expect(from).toEqual(expect.arrayContaining(["Ahmed Salah", "bilal"]));
      expect(from).not.toEqual(expect.arrayContaining(["Head Office"]));
      expect(to).toEqual(expect.arrayContaining(["Head Office", "North Depot"]));
      expect(to).not.toEqual(expect.arrayContaining(["Ahmed Salah"]));
    });

    it("re-offers the right entities when the type changes, and clears the chosen ends", async () => {
      serve();
      await ready();
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );
      fireEvent.change(screen.getByTestId("relationship-from-select"), { target: { value: "11" } });
      // The To end is deliberately a UNIT, which is still a legal choice
      // for the next type: a stale From selection merely stops matching
      // any option and renders blank on its own, so it cannot tell a form
      // that clears its ends from one that does not. A stale TO selection
      // would survive, visibly, as a choice the user never made for this
      // type.
      fireEvent.change(screen.getByTestId("relationship-to-select"), { target: { value: "21" } });

      // reports_to is unit -> unit, so BOTH ends become units.
      fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:from" } });

      await waitFor(() => {
        const from = within(screen.getByTestId("relationship-from-select"))
          .getAllByRole("option")
          .map((o) => o.textContent);
        expect(from).toEqual(expect.arrayContaining(["Head Office", "North Depot"]));
        expect(from).not.toEqual(expect.arrayContaining(["Ahmed Salah"]));
      });
      expect(screen.getByTestId("relationship-from-select")).toHaveValue("");
      expect(screen.getByTestId("relationship-to-select")).toHaveValue("");
    });

    it("creates the relationship, with the chosen ends the right way round", async () => {
      serve((path, init) =>
        init?.method === "POST"
          ? Promise.resolve({ id: 103, relationship_type_id: 5, from_entity_id: 12, to_entity_id: 21, attrs: {} })
          : undefined
      );
      await ready();
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );

      fireEvent.change(screen.getByTestId("relationship-from-select"), { target: { value: "12" } });
      fireEvent.change(screen.getByTestId("relationship-to-select"), { target: { value: "21" } });
      fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));

      await waitFor(() => expect(writes()).toHaveLength(1));
      expect(writes()[0]).toEqual({
        method: "POST",
        path: "/api/v1/relationships",
        body: { relationship_type_id: 5, from_entity_id: 12, to_entity_id: 21 },
      });
    });

    it("refuses an unfinished form without sending anything, and lists both ends", async () => {
      serve();
      await ready();

      fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
      await flush();

      expect(writes()).toHaveLength(0);
      const summary = screen.getByTestId("form-errors");
      expect(summary).toHaveTextContent(/From: choose an entity/i);
      expect(summary).toHaveTextContent(/To: choose an entity/i);
    });

    it("puts a cardinality refusal on the end it is about, in the From/To vocabulary", async () => {
      serve((path, init) =>
        init?.method === "POST"
          ? Promise.reject(
              new ApiError(
                422,
                JSON.stringify({
                  detail: [
                    {
                      loc: ["body", "works_in"],
                      msg: 'relationship "works_in": source already has a target',
                      kind: "cardinality",
                    },
                  ],
                })
              )
            )
          : undefined
      );
      await ready();
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );
      fireEvent.change(screen.getByTestId("relationship-from-select"), { target: { value: "11" } });
      fireEvent.change(screen.getByTestId("relationship-to-select"), { target: { value: "21" } });
      fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));

      await waitFor(() =>
        expect(screen.getByTestId("form-errors")).toHaveTextContent(/allows each From entity at most one To entity/)
      );
      expect(screen.getByTestId("relationship-from-select")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByTestId("relationship-to-select")).not.toHaveAttribute("aria-invalid");
      expect(screen.getByTestId("form-errors").textContent).not.toMatch(/source|target/);
    });

    it("leaves a cycle at form level, because it is about the pair", async () => {
      serve((path, init) =>
        init?.method === "POST"
          ? Promise.reject(
              new ApiError(
                422,
                JSON.stringify({
                  detail: [
                    {
                      loc: ["body", "reports_to"],
                      msg: 'relationship "reports_to": would create a cycle',
                      kind: "cycle",
                    },
                  ],
                })
              )
            )
          : undefined
      );
      await ready();
      fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:from" } });
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );
      fireEvent.change(screen.getByTestId("relationship-from-select"), { target: { value: "22" } });
      fireEvent.change(screen.getByTestId("relationship-to-select"), { target: { value: "21" } });
      fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));

      await waitFor(() =>
        expect(screen.getByTestId("relationship-general-error")).toHaveTextContent(/would create a cycle/)
      );
      expect(screen.getByTestId("relationship-from-select")).not.toHaveAttribute("aria-invalid");
      expect(screen.getByTestId("relationship-to-select")).not.toHaveAttribute("aria-invalid");
    });

    it("says the two are already connected when the unique constraint refuses", async () => {
      serve((path, init) =>
        init?.method === "POST"
          ? Promise.reject(
              new ApiError(
                409,
                JSON.stringify({
                  detail:
                    "a relationship row with the same relationship_type_id_from_entity_id_to_entity_id already exists",
                })
              )
            )
          : undefined
      );
      await ready();
      await waitFor(() =>
        expect(within(screen.getByTestId("relationship-from-select")).getAllByRole("option").length).toBeGreaterThan(1)
      );
      fireEvent.change(screen.getByTestId("relationship-from-select"), { target: { value: "11" } });
      fireEvent.change(screen.getByTestId("relationship-to-select"), { target: { value: "22" } });
      fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));

      await waitFor(() =>
        expect(screen.getByTestId("relationship-general-error")).toHaveTextContent(
          /already connected by this relationship type/i
        )
      );
    });

    it("explains the type's cardinality, and that the database is the one enforcing it", async () => {
      serve();
      await ready();
      expect(screen.getByText(/Many to one\. The database enforces this on every relationship\./)).toBeInTheDocument();

      fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:from" } });
      await waitFor(() =>
        expect(screen.getByText(/a hierarchy: the From end is the parent/i)).toBeInTheDocument()
      );
    });
  });

  describe("deleting one", () => {
    async function listed() {
      localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
      renderPage();
      await waitFor(() => expect(dataRows()).toHaveLength(2));
    }

    it("asks first, naming the type and both entities, and does nothing on cancel", async () => {
      serve((path, init) => (init?.method === "DELETE" ? Promise.resolve(null) : undefined));
      const confirm = vi.fn(() => false);
      window.confirm = confirm;
      await listed();

      fireEvent.click(within(screen.getByTestId("relationship-101")).getByRole("button", { name: /^Delete/ }));

      const message = (confirm.mock.calls[0] as unknown as [string])[0];
      expect(message).toContain("works_in");
      expect(message.indexOf("Ahmed Salah")).toBeLessThan(message.indexOf("North Depot"));
      expect(message).toMatch(/entities at either end are not deleted/i);
      await flush();
      expect(writes()).toHaveLength(0);
    });

    it("deletes on confirm and names what went", async () => {
      serve((path, init) => (init?.method === "DELETE" ? Promise.resolve(null) : undefined));
      window.confirm = vi.fn(() => true);
      await listed();

      fireEvent.click(within(screen.getByTestId("relationship-102")).getByRole("button", { name: /^Delete/ }));

      await waitFor(() => expect(writes()).toHaveLength(1));
      expect(writes()[0]).toMatchObject({ method: "DELETE", path: "/api/v1/relationships/102" });
      const toast = await screen.findByRole("status");
      expect(toast).toHaveTextContent("reports_to");
      expect(toast).toHaveTextContent("Head Office");
      expect(toast).toHaveTextContent("North Depot");
    });

    it("gives each row's Delete button a name that says which row it is", async () => {
      // Four identical "Delete" buttons in a table is a screen-reader trap:
      // the accessible name has to carry the row.
      serve();
      await listed();
      expect(
        screen.getByRole("button", { name: /Delete the works_in relationship from Ahmed Salah to North Depot/i })
      ).toBeInTheDocument();
    });
  });
});
