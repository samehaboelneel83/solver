import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelVersions from "./ModelVersions";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const PROBLEMS = {
  items: [
    { id: 11, domain_id: 7, name: "rota", owner: "ops", created_at: "2026-09-01T08:00:00Z" },
    { id: 12, domain_id: 7, name: "budget", owner: null, created_at: "2026-09-02T08:00:00Z" },
  ],
  total: 2,
};

// Neither version order nor id order: the server sorts newest first, and a
// page that re-sorted (or sorted by id) would be caught.
const VERSIONS = {
  items: [
    { id: 501, problem_id: 11, version: 7, ir_hash: "aaa111", note: "with overtime", created_at: "2026-09-19T10:00:00Z" },
    { id: 503, problem_id: 11, version: 2, ir_hash: "ccc333", note: null, created_at: "2026-09-17T10:00:00Z" },
    { id: 502, problem_id: 11, version: 5, ir_hash: "bbb222", note: "baseline", created_at: "2026-09-18T10:00:00Z" },
  ],
  total: 3,
};

const VERSION_501 = {
  ...VERSIONS.items[0],
  ir: { objective: "minimise_cost", constraints: [{ name: "no_overlap", hard: true }] },
};

function serve(over: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string) => {
    for (const [prefix, value] of Object.entries(over)) {
      if (path.startsWith(prefix)) {
        return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
      }
    }
    if (path.startsWith("/api/problem/")) return Promise.resolve(PROBLEMS);
    if (path.startsWith("/api/v1/problems/11/versions")) return Promise.resolve(VERSIONS);
    if (path.startsWith("/api/v1/problems/12/versions")) return Promise.resolve({ items: [], total: 0 });
    if (path.startsWith("/api/v1/versions/501")) return Promise.resolve(VERSION_501);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function paths(): string[] {
  return mockFetch.mock.calls.map((call) => call[0] as string);
}

function renderPage(entry = "/versions") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/versions" element={<ModelVersions />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
});

describe("ModelVersions: choosing what to show", () => {
  it("asks for a domain first, and requests nothing, when none is selected", async () => {
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    serve();
    renderPage();

    expect(await screen.findByText(/choose a domain/i)).toBeInTheDocument();
    expect(paths()).toHaveLength(0);
  });

  it("scopes the problem list to the selected domain", async () => {
    serve();
    renderPage();

    await screen.findByRole("table", { name: /versions of rota/i });
    const problemCall = paths().find((path) => path.startsWith("/api/problem/"));
    expect(problemCall).toContain("f_domain_id=7");
  });

  it("explains how to get a problem when the domain has none, and asks for no versions", async () => {
    serve({ "/api/problem/": { items: [], total: 0 } });
    renderPage();

    expect(await screen.findByRole("link", { name: /problems page/i })).toHaveAttribute("href", "/public/problem");
    expect(paths().some((path) => path.includes("/versions"))).toBe(false);
  });

  it("shows the problem named in the query string rather than the first one", async () => {
    serve();
    renderPage("/versions?problem=12");

    expect(await screen.findByText(/no versions of this problem yet/i)).toBeInTheDocument();
    expect(paths()).toContain("/api/v1/problems/12/versions?limit=50");
    expect(paths().some((path) => path.startsWith("/api/v1/problems/11/"))).toBe(false);
  });
});

describe("ModelVersions: problems beyond the first page", () => {
  it("opens a linked problem that is not on the first page, by its id", async () => {
    serve({
      "/api/problem/900": { id: 900, domain_id: 7, name: "far down the list" },
      "/api/v1/problems/900/versions": { items: [], total: 0 },
    });
    renderPage("/versions?problem=900");
    expect(await screen.findByText(/no versions of this problem yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Problem")).toHaveValue("900");
    expect(screen.getByRole("option", { name: "far down the list" })).toBeInTheDocument();
  });

  it("refuses a linked problem from another domain rather than substituting one", async () => {
    serve({ "/api/problem/900": { id: 900, domain_id: 8, name: "elsewhere" } });
    renderPage("/versions?problem=900");
    expect(await screen.findByText("This problem is not available here")).toBeInTheDocument();
    expect(paths().some((path) => path.startsWith("/api/v1/problems/"))).toBe(false);
  });
});

describe("ModelVersions: the list", () => {
  it("lists the versions in the order the API returned them, newest first", async () => {
    serve();
    renderPage();

    const table = await screen.findByRole("table", { name: /versions of rota/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("rowheader")[0].textContent?.trim())).toEqual(["7", "2", "5"]);
    // The note and the hash belong to their own version, not to the row above.
    const cells = within(rows[0]).getAllByRole("cell");
    // Asserted through the machine-readable timestamp: the visible text is
    // the reader's own locale and time zone, which the test runner's is not.
    expect(cells[0].querySelector("time")?.getAttribute("datetime")).toBe("2026-09-19T10:00:00Z");
    expect(cells[1].textContent?.trim()).toBe("aaa111");
    expect(cells[2].textContent?.trim()).toBe("with overtime");
    expect(within(rows[1]).getAllByRole("cell")[2].textContent?.trim()).toBe("—");
  });

  it("says so when a problem has no versions, and explains where they come from", async () => {
    serve();
    renderPage("/versions?problem=12");

    const note = await screen.findByText(/no versions of this problem yet/i);
    expect(note.textContent).toMatch(/model editor/i);
    expect(within(note).getByRole("link", { name: "Model editor" })).toHaveAttribute("href", "/model");
  });

  it("offers nothing that would create, change or delete a version", async () => {
    serve();
    renderPage();

    await screen.findByRole("table", { name: /versions of rota/i });
    for (const button of screen.getAllByRole("button")) {
      expect(button.textContent ?? "").not.toMatch(/new|create|edit|delete|save/i);
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText(/immutable/i)).toBeInTheDocument();
  });
});

describe("ModelVersions: the IR viewer", () => {
  it("fetches and shows one version's IR as formatted JSON", async () => {
    serve();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /version 7/i }));

    const ir = await screen.findByTestId("version-ir");
    await waitFor(() => expect(ir.textContent).toContain("no_overlap"));
    // Formatted, not a single JSON line.
    expect(ir.textContent).toContain('"objective": "minimise_cost"');
    expect(ir.textContent?.split("\n").length).toBeGreaterThan(3);
    expect(paths()).toContain("/api/v1/versions/501");
  });

  it("asks for no IR until a version is chosen", async () => {
    serve();
    renderPage();

    await screen.findByRole("table", { name: /versions of rota/i });
    expect(paths().some((path) => path.startsWith("/api/v1/versions/"))).toBe(false);
    expect(screen.getByText(/choose a version/i)).toBeInTheDocument();
  });

  it("scrolls the IR inside its own container", async () => {
    serve();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /version 7/i }));
    const ir = await screen.findByTestId("version-ir");
    expect(ir.className).toMatch(/overflow-auto/);
    expect(ir.className).toMatch(/max-h-/);
  });

  it("opens the version named in the query string on load", async () => {
    serve();
    renderPage("/versions?problem=11&version=501");

    const ir = await screen.findByTestId("version-ir");
    await waitFor(() => expect(ir.textContent).toContain("minimise_cost"));
  });
});
