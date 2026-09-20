import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelEditor from "./ModelEditor";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const PROBLEMS = { items: [{ id: 1, name: "weekly_rota", domain_id: 1 }], total: 1 };

const ENTITY_TYPES = {
  items: [
    {
      id: 5,
      domain_id: 1,
      name: "employee",
      role: "agent",
      colour: null,
      attributes: [
        { id: 1, entity_type_id: 5, name: "hours_per_week", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 6, domain_id: 1, name: "day", role: "time", colour: null, attributes: [] },
  ],
  total: 2,
};

const PARAMETERS = {
  items: [{ id: 9, domain_id: 1, name: "demand", index_type_ids: [6], default_value: 1, unit: null }],
  total: 1,
};

const IR_V2 = {
  version: 1,
  sets: ["employee", "day"],
  parameters: { demand: { index: ["day"] } },
  variables: { assign: { index: ["employee", "day"], domain: "binary" } },
  constraints: [
    {
      id: "c_cover",
      note: "each day is staffed",
      forall: [{ index: "d", set: "day" }],
      left: { sum: { var: "assign", index: ["e", "d"] }, over: [{ index: "e", set: "employee" }] },
      relation: ">=",
      right: { par: "demand", index: ["d"] },
      severity: "hard",
    },
  ],
  objective: { sense: "minimize", terms: [] },
};

const VERSIONS = {
  items: [
    { id: 22, problem_id: 1, version: 2, ir_hash: "bb", note: "expressed", created_at: "2026-09-20T10:00:00Z" },
    { id: 21, problem_id: 1, version: 1, ir_hash: "aa", note: "first", created_at: "2026-09-19T10:00:00Z" },
  ],
  total: 2,
};

function stub(overrides: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") {
      const write = overrides.write as ((p: string, o: typeof options) => Promise<unknown>) | undefined;
      if (write) return write(path, options);
      return Promise.resolve({ id: 23, version: 3 });
    }
    if (path.startsWith("/api/problem")) return Promise.resolve(overrides.problems ?? PROBLEMS);
    if (path.startsWith("/api/v1/problems/1/versions")) return Promise.resolve(overrides.versions ?? VERSIONS);
    if (path.startsWith("/api/v1/versions/21")) {
      return Promise.resolve({ ...VERSIONS.items[1], ir: overrides.irV1 ?? { ...IR_V2, constraints: [] } });
    }
    if (path.startsWith("/api/v1/versions/22")) {
      return Promise.resolve({ ...VERSIONS.items[0], ir: IR_V2 });
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(ENTITY_TYPES);
    if (path.startsWith("/api/v1/parameters")) return Promise.resolve(PARAMETERS);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function renderPage(entry = "/model") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
          <ModelEditor />
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

describe("ModelEditor", () => {
  it("edits from the latest version by default", async () => {
    renderPage();

    expect(await screen.findByLabelText(/starting from/i)).toHaveValue("22");
    expect(await screen.findByDisplayValue("c_cover")).toBeInTheDocument();
  });

  it("offers to start a model when the problem has none", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));

    // From nothing: no sets declared, no rules, and the declarations editor
    // is what appears first, because a rule cannot be written before the
    // model says what it ranges over.
    expect(await screen.findByText(/starting a model from nothing/i)).toBeInTheDocument();
    const sets = screen.getByRole("group", { name: "Sets" });
    expect(within(sets).getByRole("checkbox", { name: "employee" })).not.toBeChecked();
  });

  it("starts from an older version when one is chosen, without touching it", async () => {
    renderPage();
    const chooser = await screen.findByLabelText(/starting from/i);

    fireEvent.change(chooser, { target: { value: "21" } });

    // Version 1 has no rules; seeing them gone is how we know the draft was
    // rebuilt from the chosen version rather than kept from the last one.
    await waitFor(() => expect(screen.queryByDisplayValue("c_cover")).not.toBeInTheDocument());
    // The page passes through a loading state while the chosen version is
    // fetched, so wait for the note rather than asserting the instant after.
    expect(await screen.findByText(/never something this overwrites/i)).toBeInTheDocument();
  });

  it("publishes the declarations and rules as a new version", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /publish a new version/i }));

    await waitFor(() => expect(write).toHaveBeenCalled());
    const [path, options] = write.mock.calls[0];
    expect(path).toBe("/api/v1/problems/1/versions");
    const sent = JSON.parse(options.body).ir;
    // The whole model travels, not only the rules: a published version that
    // dropped its declarations would refuse to compile.
    expect(sent.sets).toEqual(["employee", "day"]);
    expect(sent.parameters).toEqual({ demand: { index: ["day"] } });
    expect(sent.variables).toEqual({ assign: { index: ["employee", "day"], domain: "binary" } });
    expect(sent.constraints).toHaveLength(1);
  });

  it("declaring a set makes it available to the rules immediately", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));

    const sets = screen.getByRole("group", { name: "Sets" });
    fireEvent.click(within(sets).getByRole("checkbox", { name: "day" }));
    fireEvent.click(screen.getByRole("button", { name: /add a rule/i }));

    // The new rule's binding offers `day` -- if the term editor read the
    // stored version instead of the draft, the two halves of this page would
    // disagree about what the model is.
    const over = await screen.findByLabelText("Over");
    expect(Array.from((over as HTMLSelectElement).options).map((o) => o.value)).toContain("day");
  });

  it("reports a server refusal against the model rather than losing the edit", async () => {
    const { ApiError } = await import("../api/client");
    stub({
      write: () =>
        Promise.reject(
          new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "ir", "constraints", 0], msg: "no expression" }] }))
        ),
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /publish a new version/i }));

    expect(await screen.findByText(/no expression/i)).toBeInTheDocument();
    // The work is still on screen.
    expect(screen.getByDisplayValue("c_cover")).toBeInTheDocument();
  });
});
