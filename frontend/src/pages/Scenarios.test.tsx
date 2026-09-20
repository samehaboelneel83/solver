import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Scenarios, { describePatch, fromPatch, toPatch } from "./Scenarios";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const PROBLEMS = { items: [{ id: 1, name: "weekly_rota", domain_id: 1 }], total: 1 };
const VERSIONS = {
  items: [
    { id: 22, problem_id: 1, version: 2, ir_hash: "bb", note: "expressed", created_at: "2026-09-20T10:00:00Z" },
    { id: 21, problem_id: 1, version: 1, ir_hash: "aa", note: "first", created_at: "2026-09-19T10:00:00Z" },
  ],
  total: 2,
};
const IR_22 = {
  constraints: [
    { id: "c_cover_demand", note: "each day/shift is staffed", severity: "hard" },
    { id: "c_max_hours", note: "weekly hours", severity: "hard" },
  ],
};
// Version 1 has a rule version 2 does not: choosing it must drop a choice
// that no longer applies.
const IR_21 = { constraints: [{ id: "c_old_only", note: "gone in v2", severity: "hard" }] };

const SCENARIOS = {
  items: [
    {
      id: 7,
      problem_id: 1,
      model_version_id: 22,
      name: "relaxed_cover",
      patch: { soften: { c_cover_demand: 100 } },
      created_at: "2026-09-20T10:00:00Z",
    },
  ],
  total: 1,
};

function stub(overrides: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") {
      const write = overrides.write as ((p: string, o: typeof options) => Promise<unknown>) | undefined;
      if (write) return write(path, options);
      return Promise.resolve({ id: 8 });
    }
    if (path.startsWith("/api/problem")) return Promise.resolve(overrides.problems ?? PROBLEMS);
    if (path.startsWith("/api/v1/problems/1/versions")) return Promise.resolve(overrides.versions ?? VERSIONS);
    if (path.startsWith("/api/v1/versions/21")) return Promise.resolve({ ...VERSIONS.items[1], ir: IR_21 });
    if (path.startsWith("/api/v1/versions/22")) return Promise.resolve({ ...VERSIONS.items[0], ir: IR_22 });
    if (path.startsWith("/api/v1/scenarios")) return Promise.resolve(overrides.scenarios ?? SCENARIOS);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/scenarios"]}>
          <Scenarios />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
  stub();
});

describe("patch conversion", () => {
  it("round-trips the three verbs", () => {
    const patch = { disable: ["a"], harden: ["b"], soften: { c: 50 } };

    expect(toPatch(fromPatch(patch))).toEqual(patch);
  });

  it("leaves an untouched rule out of the patch entirely", () => {
    // "leave as it is" is the absence of an instruction, not a fourth verb:
    // a patch listing every rule would be a different document.
    expect(toPatch({ c_cover: { choice: "as_is", weight: 100 } })).toEqual({});
  });

  it("reads a patch back in words", () => {
    expect(describePatch({ soften: { c_cover: 100 } })).toMatch(/bends c_cover at 100/);
    expect(describePatch({})).toMatch(/asks the model as written/);
  });
});

describe("Scenarios", () => {
  it("lists what each scenario changes, not only its name", async () => {
    renderPage();

    expect(await screen.findByText("relaxed_cover")).toBeInTheDocument();
    expect(screen.getByText(/bends c_cover_demand at 100/)).toBeInTheDocument();
  });

  it("offers the version's own rules to patch", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /new scenario/i }));

    // A patch naming a rule the version does not declare is refused by the
    // server; offering the rules means it cannot be written at all.
    expect(await screen.findByLabelText(/what to do with c_cover_demand/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/what to do with c_max_hours/i)).toBeInTheDocument();
  });

  it("asks for a cost only when a rule is allowed to bend", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /new scenario/i }));
    const choice = await screen.findByLabelText(/what to do with c_cover_demand/i);

    expect(screen.queryByLabelText(/cost of bending/i)).not.toBeInTheDocument();
    fireEvent.change(choice, { target: { value: "soften" } });

    expect(screen.getByLabelText(/cost of bending c_cover_demand/i)).toHaveValue("100");
  });

  it("creates a scenario carrying the choices made", async () => {
    const write = vi.fn().mockResolvedValue({ id: 8 });
    stub({ write });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /new scenario/i }));

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "no_hours_cap" } });
    fireEvent.change(await screen.findByLabelText(/what to do with c_max_hours/i), {
      target: { value: "disable" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() => expect(write).toHaveBeenCalled());
    const body = JSON.parse(write.mock.calls[0][1].body);
    expect(body.name).toBe("no_hours_cap");
    expect(body.model_version_id).toBe(22);
    expect(body.patch).toEqual({ disable: ["c_max_hours"] });
  });

  it("drops a choice that the newly chosen version does not have", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
    // The scenario softens c_cover_demand, which exists in version 2 only.
    expect(await screen.findByLabelText(/cost of bending c_cover_demand/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/of version/i), { target: { value: "21" } });

    // Version 1 has no such rule; keeping the choice would send a patch the
    // server refuses.
    await waitFor(() =>
      expect(screen.queryByLabelText(/what to do with c_cover_demand/i)).not.toBeInTheDocument()
    );
    expect(await screen.findByLabelText(/what to do with c_old_only/i)).toBeInTheDocument();
  });

  it("will not create a scenario with no name", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /new scenario/i }));

    expect(screen.getByRole("button", { name: /^create$/i })).toBeDisabled();
  });

  it("says a problem needs a model before it can have a scenario", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();

    expect(await screen.findByText(/a scenario patches one/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new scenario/i })).not.toBeInTheDocument();
  });

  it("reports a server refusal without losing the form", async () => {
    const { ApiError } = await import("../api/client");
    stub({
      write: () => Promise.reject(new ApiError(409, JSON.stringify({ detail: "name already taken" }))),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /new scenario/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "relaxed_cover" } });

    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    // By text rather than by role: a toast region is also an alert, and it
    // can win the race.
    expect(await screen.findByText(/name already taken/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("relaxed_cover");
  });
});
