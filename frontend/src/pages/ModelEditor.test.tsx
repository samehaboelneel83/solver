import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelEditor from "./ModelEditor";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { clearDraft } from "../model/draftStore";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

// Blockly cannot draw in jsdom (it measures text on a canvas), so the Blocks
// tab's editor is a stand-in here: these tests are about the page's side --
// what the tab shows, and what an edit made in it does to the draft. The
// editor itself is tested headless (BlocksEditor.test.ts) and live.
vi.mock("../components/BlocksEditor", () => ({
  default: ({ ir, onChange }: { ir: Record<string, unknown>; onChange: (ir: Record<string, unknown>, paths: Map<string, unknown>, outside: number) => void }) => (
    <div data-testid="blocks-editor">
      <span data-testid="blocks-ir">{JSON.stringify(ir)}</span>
      <button type="button" onClick={() => onChange({ ...ir, constraints: [...(ir.constraints as unknown[]).map((c) => ({ ...(c as object), note: "changed in blocks" }))] }, new Map(), 0)}>
        edit in blocks
      </button>
      <button type="button" onClick={() => onChange(ir, new Map(), 1)}>drop a block beside the model</button>
    </div>
  ),
}));

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
    if (path.startsWith("/api/v1/classify")) {
      const ir = options?.body ? (JSON.parse(options.body) as { ir?: { variables?: object; constraints?: { severity?: string }[] } }).ir : {};
      const variables = Object.keys(ir?.variables ?? {});
      if (variables.length === 0) {
        return Promise.resolve({
          model_class: "trivial",
          needs: ["linear"],
          reasons: ["no variables, so nothing is decided"],
          planner: ["nothing is decided yet"],
          empty_ranges: [],
          would_solve: "A combinatorial solver will take this by default.",
        });
      }
      const soft = (ir?.constraints ?? []).some((c) => c.severity === "soft");
      return Promise.resolve({
        model_class: "IP",
        needs: soft ? ["integral", "linear", "soft-constraints"] : ["integral", "linear"],
        reasons: ["every variable is binary", "all terms are linear (the contract refuses a product of two variables)"],
        planner: [
          "every decision is yes or no",
          "every rule is linear",
          ...(soft ? ["at least one rule can bend, at a cost"] : []),
        ],
        empty_ranges: (overrides.emptyRanges as unknown[]) ?? [],
        would_solve:
          "wouldSolve" in overrides
            ? (overrides.wouldSolve as string | null)
            : "A combinatorial solver will take this by default.",
      });
    }
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
      return Promise.resolve({ ...VERSIONS.items[0], ir: overrides.ir ?? IR_V2 });
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(overrides.entityTypes ?? ENTITY_TYPES);
    if (path.startsWith("/api/v1/parameters")) return Promise.resolve(PARAMETERS);
    if (path.startsWith("/api/v1/relationship-types")) {
      return Promise.resolve(overrides.relationshipTypes ?? { items: [], total: 0 });
    }
    if (path.startsWith("/api/v1/me")) {
      return Promise.resolve(
        overrides.me ?? {
          username: "admin",
          display_name: "Administrator",
          capabilities: ["domain.edit", "model.publish", "run.submit"],
        }
      );
    }
    if (path.startsWith("/api/template")) {
      return Promise.resolve(overrides.templates ?? { items: [], total: 0 });
    }
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
  // Drafts persist (the shared draft store): one test's edit must not be
  // the next test's starting point. `clearDraft` also empties the store's
  // in-memory fallback, which a storage-refusing test fills.
  localStorage.clear();
  clearDraft(1);
  vi.restoreAllMocks();
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

  it("offers a template when the problem has no model yet", async () => {
    const write = vi.fn().mockResolvedValue({
      template_id: 1,
      problem_id: 1,
      model_version_id: 40,
      scenario_id: 9,
    });
    stub({
      versions: { items: [], total: 0 },
      templates: { items: [{ id: 1, name: "weekly_rota", ir_version: "1", domain_seed: {}, default_ir: {} }], total: 1 },
      write,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /start from weekly_rota/i }));

    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(write.mock.calls[0][0]).toBe("/api/v1/templates/1/apply");
    expect(JSON.parse(write.mock.calls[0][1].body)).toEqual({ problem_id: 1, domain_id: 1 });
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
    const over = await screen.findByLabelText("Set");
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

  it("opens a pre-contract sketch without crashing, and says why it cannot be edited yet", async () => {
    // The live demo still carries version 1 of this shape: an id, a note,
    // and nothing to solve. `describeTerm` used `'const' in term` on the
    // missing left-hand side and took the whole editor down.
    stub({
      irV1: {
        sets: ["employee", "day"],
        parameters: { demand: { index: ["day"] } },
        variables: { assign: { index: ["employee", "day"], domain: "binary" } },
        constraints: [
          { id: "c_cover_demand", note: "each day/shift is staffed to at least demand[day, shift]" },
        ],
        objective: { sense: "minimize", terms: [{ id: "o_cost", weight: 1 }] },
      },
    });
    renderPage();
    fireEvent.change(await screen.findByLabelText(/starting from/i), { target: { value: "21" } });

    expect(await screen.findByDisplayValue("c_cover_demand")).toBeInTheDocument();
    expect(screen.getByText(/this rule is named but not expressed/i)).toBeInTheDocument();
    // Published at the current version, the refusal is the rule itself, not
    // the sketch's missing version.
    expect(screen.getAllByRole("alert").some((alert) => /c_cover_demand. has no left/.test(alert.textContent ?? ""))).toBe(true);
    expect(screen.getByText(/named but has nothing to count/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Kind of term")).not.toBeInTheDocument();
  });

  it("opens a scheduling model and publishes it unchanged", async () => {
    // Version 2 intervals and a no_overlap rule: the editor must neither
    // crash, call the rule unexpressed, offer its Strength, nor drop an
    // interval's start, end and size on publish.
    const task = { index: ["day"], domain: "interval", start: "begin", end: "finish", size: "demand" };
    const room = {
      id: "c_room",
      no_overlap: { interval: { var: "task", index: ["d"] }, over: [{ index: "d", set: "day" }] },
      severity: "hard",
    };
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        version: 2,
        sets: ["day"],
        parameters: { demand: { index: ["day"] } },
        variables: {
          begin: { index: ["day"], domain: "integer", lower: 0, upper: 20 },
          finish: { index: ["day"], domain: "integer", lower: 0, upper: 20 },
          task,
        },
        constraints: [room],
      },
    });
    renderPage();

    expect(await screen.findByText("no two of task[d] (d in day) overlap")).toBeInTheDocument();
    expect(screen.getByText(/a scheduling rule is always required/i)).toBeInTheDocument();
    expect(screen.getByText(/task is a span of time: from begin to finish, lasting demand/i)).toBeInTheDocument();
    expect(screen.queryByText(/named but not expressed/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Strength")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.variables.task).toEqual(task);
    expect(sent.constraints).toEqual([room]);
  });

  it("builds a scheduling rule: a shared capacity over the intervals, published", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        version: 2,
        sets: ["day"],
        parameters: { demand: { index: ["day"] } },
        variables: {
          begin: { index: ["day"], domain: "integer", lower: 0, upper: 20 },
          finish: { index: ["day"], domain: "integer", lower: 0, upper: 20 },
          task: { index: ["day"], domain: "interval", start: "begin", end: "finish", size: "demand" },
        },
        constraints: [],
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /add a scheduling rule/i }));
    expect(screen.getByText("no two of task[d] (d in day) overlap")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("The intervals"), { target: { value: "cumulative" } });
    // The second number is the capacity ("Out of a capacity of").
    fireEvent.change(screen.getAllByLabelText("Value")[1], { target: { value: "2" } });

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints).toEqual([
      {
        id: "c_1",
        cumulative: {
          interval: { var: "task", index: ["d"] },
          over: [{ index: "d", set: "day" }],
          demand: { const: 1 },
          capacity: { const: 2 },
        },
        severity: "hard",
      },
    ]);
  });

  const GRID_TYPES = {
    items: [
      { id: 7, domain_id: 1, name: "cell", role: "location", colour: null, attributes: [] },
      { id: 8, domain_id: 1, name: "zone", role: "org", colour: null, attributes: [] },
    ],
    total: 2,
  };
  const ADJACENT = {
    items: [{ id: 3, domain_id: 1, name: "adjacent", from_type_id: 7, to_type_id: 7, cardinality: "many_to_many", is_hierarchy: false }],
    total: 1,
  };
  const ZONES = {
    version: 2,
    sets: ["cell", "zone"],
    parameters: {},
    variables: { assign: { index: ["cell", "zone"], domain: "binary" } },
    constraints: [] as unknown[],
  };

  it("opens a connected rule and publishes it unchanged, relationship declared", async () => {
    const rule = {
      id: "c_zones",
      connected: {
        assign: { var: "assign", index: ["u", "z"] },
        units: { index: "u", set: "cell" },
        groups: { index: "z", set: "zone" },
        via: "adjacent",
        empty: "allowed",
      },
      severity: "hard",
    };
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write, entityTypes: GRID_TYPES, relationshipTypes: ADJACENT, ir: { ...ZONES, relationships: ["adjacent"], constraints: [rule] } });
    renderPage();

    expect(await screen.findByText("each zone is one connected piece of cell (or empty) over adjacent")).toBeInTheDocument();
    expect(screen.queryByText(/named but not expressed/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Strength")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints).toEqual([rule]);
    expect(sent.relationships).toEqual(["adjacent"]);
  });

  it("builds a connected rule from the admissible choices, and publishes it", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write, entityTypes: GRID_TYPES, relationshipTypes: ADJACENT, ir: ZONES });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /add a connected rule/i }));
    expect(screen.getByText("each zone is one connected piece of cell over adjacent")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.relationships).toEqual(["adjacent"]);
    expect(sent.constraints).toEqual([
      {
        id: "c_1",
        connected: {
          assign: { var: "assign", index: ["c", "z"] },
          units: { index: "c", set: "cell" },
          groups: { index: "z", set: "zone" },
          via: "adjacent",
          empty: "forbidden",
        },
        severity: "hard",
      },
    ]);
  });

  it("offers no connected rule when nothing could be one", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("c_cover")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add a connected rule/i })).not.toBeInTheDocument();
  });

  it("makes a rule conditional on a yes-or-no decision, and publishes the switch", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        ...IR_V2,
        variables: { ...IR_V2.variables, staffed: { index: ["day"], domain: "binary" } },
      },
    });
    renderPage();

    fireEvent.click(await screen.findByLabelText(/only while a yes-or-no decision is set/i));
    fireEvent.change(screen.getByLabelText("Switch"), { target: { value: "staffed" } });
    fireEvent.change(screen.getByLabelText("is"), { target: { value: "0" } });
    expect(screen.getByText(/only while staffed\[d\] is no/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints[0].when).toEqual({ var: "staffed", index: ["d"], is: 0 });
    // Started from a version 1 model: published as 2, which a when needs.
    expect(sent.version).toBe(2);
  });

  it("drops the condition when a rule is made preferred, and offers none then", async () => {
    stub({
      ir: {
        ...IR_V2,
        variables: { ...IR_V2.variables, staffed: { index: ["day"], domain: "binary" } },
        constraints: [{ ...IR_V2.constraints[0], when: { var: "staffed", index: ["d"], is: 1 } }],
      },
    });
    renderPage();

    const toggle = await screen.findByLabelText(/only while a yes-or-no decision is set/i);
    expect(toggle).toBeChecked();
    fireEvent.change(screen.getByLabelText("Strength"), { target: { value: "soft" } });
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeDisabled();
    expect(screen.getByText(/a preferred rule can already be broken at a cost/i)).toBeInTheDocument();
  });

  it("publishes a parameter's uncertainty as declared", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    const uncertain = { index: ["day"], uncertainty: { kind: "interval", deviation: 0.1, gamma: 2 } };
    stub({ write, ir: { ...IR_V2, parameters: { demand: uncertain } } });
    renderPage();

    expect((await screen.findByLabelText(/demand may be off by up to/i)) as HTMLInputElement).toHaveValue("10");
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(JSON.parse(write.mock.calls[0][1].body).ir.parameters.demand).toEqual(uncertain);
  });

  it("reads a soft constraint's weight from the document, not an invented key", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [{ ...IR_V2.constraints[0], severity: "soft", weight: 4 }],
      },
    });
    renderPage();

    expect(await screen.findByLabelText(/how much it matters/i)).toHaveValue("4");
  });

  it("drops the cost when a soft rule is made mandatory", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        ...IR_V2,
        constraints: [{ ...IR_V2.constraints[0], severity: "soft", weight: 4 }],
      },
    });
    renderPage();
    await screen.findByLabelText(/how much it matters/i);

    fireEvent.change(screen.getByLabelText("Strength"), {
      target: { value: "hard" },
    });
    expect(screen.queryByLabelText(/how much it matters/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints[0].severity).toBe("hard");
    expect(sent.constraints[0]).not.toHaveProperty("weight");
  });

  it("gives a soft rule a cost of 1 when it was mandatory", async () => {
    renderPage();
    await screen.findByDisplayValue("c_cover");

    fireEvent.change(screen.getByLabelText("Strength"), {
      target: { value: "soft" },
    });
    expect(await screen.findByLabelText(/how much it matters/i)).toHaveValue("1");
  });

  it("does not let a soft cost fall below 1 in the field", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [{ ...IR_V2.constraints[0], severity: "soft", weight: 4 }],
      },
    });
    renderPage();
    const cost = await screen.findByLabelText(/how much it matters/i);
    fireEvent.change(cost, { target: { value: "0" } });
    expect(cost).toHaveValue("4");
    fireEvent.change(cost, { target: { value: "2" } });
    expect(cost).toHaveValue("2");
  });

  it("names a duplicate rule id on the field, not only at Publish", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [
          { ...IR_V2.constraints[0], id: "c_a" },
          { ...IR_V2.constraints[0], id: "c_b", note: "other" },
        ],
      },
    });
    renderPage();
    const name = await screen.findByDisplayValue("c_b");
    fireEvent.change(name, { target: { value: "c_a" } });
    expect(screen.getAllByText(/another rule is already called c_a/i).length).toBeGreaterThan(0);
    expect(name).toHaveAttribute("aria-invalid", "true");
  });

  it("gives For every, Of and That each a tree chevron", async () => {
    renderPage();
    await screen.findByDisplayValue("c_cover");
    expect(screen.getByRole("button", { name: /collapse for every/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^collapse of$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^collapse that$/i })).toBeInTheDocument();
  });

  it("shows what kind of model this is, in planner language, before publish", async () => {
    renderPage();

    const panel = await screen.findByRole("complementary", { name: /what this model is/i });
    expect(within(panel).getByText(/every decision is yes or no/i)).toBeInTheDocument();
    expect(within(panel).getByText(/every rule is linear/i)).toBeInTheDocument();
  });

  it("says which kind of solver a run would pick, without offering one", async () => {
    renderPage();

    const panel = await screen.findByRole("complementary", { name: /what this model is/i });
    expect(within(panel).getByText(/combinatorial solver/i)).toBeInTheDocument();
    expect(within(panel).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("says so when no solver this platform has can take the draft", async () => {
    stub({ wouldSolve: null });
    renderPage();

    const panel = await screen.findByRole("complementary", { name: /what this model is/i });
    expect(within(panel).getByText(/no solver this platform has/i)).toBeInTheDocument();
  });

  it("names a rule that ranges over nobody, before publish", async () => {
    stub({
      emptyRanges: [{ constraint_id: "c_north", kind: "forall", index: {} }],
    });
    renderPage();

    const panel = await screen.findByRole("complementary", { name: /rules that ranged over nobody/i });
    expect(within(panel).getByText("c_north")).toBeInTheDocument();
    expect(within(panel).getByText(/never applied to anyone/i)).toBeInTheDocument();
  });

  it("in lex order shows goal place instead of a weight that does nothing", async () => {
    stub({
      ir: {
        ...IR_V2,
        objective: {
          sense: "minimize",
          mode: "lex",
          terms: [
            { id: "o_cost", weight: 1, expression: { const: 0 } },
            { id: "o_soft", weight: 4, expression: { const: 1 } },
          ],
        },
      },
    });
    renderPage();

    expect(await screen.findByDisplayValue("o_cost")).toBeInTheDocument();
    expect(screen.getByText("1st")).toBeInTheDocument();
    expect(screen.getByText("2nd")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^weight$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/unused/i)).not.toBeInTheDocument();
  });

  it("lets a person reorder lex goals with earlier and later", async () => {
    stub({
      ir: {
        ...IR_V2,
        objective: {
          sense: "minimize",
          mode: "lex",
          terms: [
            { id: "o_cost", weight: 1, expression: { const: 0 } },
            { id: "o_soft", weight: 4, expression: { const: 1 } },
          ],
        },
      },
    });
    renderPage();
    await screen.findByDisplayValue("o_cost");

    fireEvent.click(screen.getByRole("button", { name: /make o_cost later/i }));

    const names = screen.getAllByLabelText(/^name$/i) as HTMLInputElement[];
    // Objective names are among the Name fields; the two goals stay named.
    expect(names.map((n) => n.value)).toEqual(expect.arrayContaining(["o_soft", "o_cost"]));
    // After later, o_soft is first in the objective section: its "Make earlier"
    // is gone and o_cost has "Make earlier".
    expect(screen.queryByRole("button", { name: /make o_soft earlier/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /make o_cost earlier/i })).toBeInTheDocument();
  });

  it("keeps weight when goals are mixed by weight", async () => {
    stub({
      ir: {
        ...IR_V2,
        objective: {
          sense: "minimize",
          mode: "weighted",
          terms: [{ id: "o_cost", weight: 3, expression: { const: 0 } }],
        },
      },
    });
    renderPage();

    expect(await screen.findByLabelText(/^weight$/i)).toHaveValue("3");
    expect(screen.queryByText("1st")).not.toBeInTheDocument();
  });

  it("names a new rule after the next unused set, not a generic i", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));

    const sets = screen.getByRole("group", { name: "Sets" });
    fireEvent.click(within(sets).getByRole("checkbox", { name: "employee" }));
    fireEvent.click(within(sets).getByRole("checkbox", { name: "day" }));
    fireEvent.click(screen.getByRole("button", { name: /add a rule/i }));

    expect(await screen.findByDisplayValue("c_1")).toBeInTheDocument();
    expect(screen.getByLabelText("Index")).toHaveValue("e");
    expect(screen.getByLabelText("Set")).toHaveValue("employee");
  });

  it("picks a free rule id when a middle one was removed", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [
          { ...IR_V2.constraints[0], id: "c_1" },
          { ...IR_V2.constraints[0], id: "c_3", note: "third" },
        ],
      },
    });
    renderPage();
    await screen.findByDisplayValue("c_1");

    fireEvent.click(screen.getByRole("button", { name: /add a rule/i }));
    expect(await screen.findByDisplayValue("c_2")).toBeInTheDocument();
  });

  it("picks a free goal id when a middle one was removed", async () => {
    stub({
      ir: {
        ...IR_V2,
        objective: {
          sense: "minimize",
          mode: "weighted",
          terms: [
            { id: "o_1", weight: 1, expression: { const: 0 } },
            { id: "o_3", weight: 1, expression: { const: 1 } },
          ],
        },
      },
    });
    renderPage();
    await screen.findByDisplayValue("o_1");

    fireEvent.click(screen.getByRole("button", { name: /add something to count/i }));
    expect(await screen.findByDisplayValue("o_2")).toBeInTheDocument();
  });

  it("lets a rule range over nothing by removing its last index", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        ...IR_V2,
        constraints: [
          {
            id: "c_global",
            note: "always true",
            forall: [{ index: "d", set: "day" }],
            left: { const: 0 },
            relation: "<=",
            right: { const: 1 },
            severity: "hard",
          },
        ],
        objective: {
          sense: "minimize",
          terms: [{ id: "o_1", weight: 1, expression: { const: 0 } }],
        },
      },
    });
    renderPage();
    await screen.findByDisplayValue("c_global");

    fireEvent.click(screen.getByRole("button", { name: /remove d in day/i }));

    await waitFor(() => {
      expect(screen.queryByLabelText("Index")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints[0]).not.toHaveProperty("forall");
  });

  it("drops a blank What it means rather than publishing an empty note", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write });
    renderPage();
    await screen.findByDisplayValue("c_cover");

    fireEvent.change(screen.getByLabelText(/what it means/i), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints[0]).not.toHaveProperty("note");
  });

  it("adds a global rule when no set is declared yet", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));
    fireEvent.click(screen.getByRole("button", { name: /add a rule/i }));

    expect(await screen.findByDisplayValue("c_1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Index")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add an index/i })).not.toBeInTheDocument();
  });

  it("names the rule and goal sections in planner language", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));

    expect(screen.getByRole("heading", { name: /what must be true/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /what to make best/i })).toBeInTheDocument();
    expect(screen.getByText(/no rules yet/i)).toBeInTheDocument();
  });

  it("calls a hard rule required and a soft one preferred", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [{ ...IR_V2.constraints[0], severity: "soft", weight: 4 }],
      },
    });
    renderPage();
    await screen.findByDisplayValue("c_cover");

    const strength = screen.getByLabelText("Strength") as HTMLSelectElement;
    expect(strength.options[strength.selectedIndex].text).toMatch(/preferred/i);

    fireEvent.change(strength, { target: { value: "hard" } });
    expect(
      (screen.getByLabelText("Strength") as HTMLSelectElement).options[
        (screen.getByLabelText("Strength") as HTMLSelectElement).selectedIndex
      ].text
    ).toMatch(/required/i);
  });

  it("invites a goal when the objective is empty, rather than a blank box", async () => {
    stub({ versions: { items: [], total: 0 } });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /start a model/i }));

    expect(screen.getByText(/no goals yet/i)).toBeInTheDocument();
    expect(screen.getByText(/feasibility/i)).toBeInTheDocument();
  });

  it("names a preferred rule's cost as how much it matters", async () => {
    stub({
      ir: {
        ...IR_V2,
        constraints: [{ ...IR_V2.constraints[0], severity: "soft", weight: 4 }],
      },
    });
    renderPage();
    expect(await screen.findByLabelText(/how much it matters/i)).toHaveValue("4");
  });

  it("publishes a cleared filter without an empty where key", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      entityTypes: {
        items: [
          ENTITY_TYPES.items[0],
          {
            id: 6,
            domain_id: 1,
            name: "day",
            role: "time",
            colour: null,
            attributes: [
              {
                id: 2,
                entity_type_id: 6,
                name: "is_weekend",
                data_type: "boolean",
                required: false,
                unit: null,
                enum_values: null,
                default_value: null,
              },
            ],
          },
        ],
        total: 2,
      },
      ir: {
        ...IR_V2,
        constraints: [
          {
            ...IR_V2.constraints[0],
            forall: [
              {
                index: "d",
                set: "day",
                where: [{ attr: "is_weekend", op: "=", value: true }],
              },
            ],
          },
        ],
      },
    });
    renderPage();
    await screen.findByDisplayValue("c_cover");

    fireEvent.click(screen.getByRole("button", { name: /remove condition/i }));
    // The query builder reports a removal a tick after rendering it; a
    // person cannot click Publish inside that tick, but a loaded test run
    // could, and would publish the filter it had just removed.
    await waitFor(() => expect(screen.queryByRole("button", { name: /remove condition/i })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText(/is_weekend/)).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.constraints[0].forall[0]).toEqual({ index: "d", set: "day" });
    expect(sent.constraints[0].forall[0]).not.toHaveProperty("where");
  });

  it("publishes integer bounds and drops them when the variable is yes-or-no", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({
      write,
      ir: {
        ...IR_V2,
        variables: {
          assign: { index: ["employee", "day"], domain: "binary" },
          hours: { index: ["employee"], domain: "integer", lower: 0, upper: 40 },
        },
      },
    });
    renderPage();
    await screen.findByLabelText(/hours decides/i);

    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    const sent = JSON.parse(write.mock.calls[0][1].body).ir;
    expect(sent.variables.hours).toEqual({
      index: ["employee"],
      domain: "integer",
      lower: 0,
      upper: 40,
    });
    expect(sent.variables.assign).toEqual({
      index: ["employee", "day"],
      domain: "binary",
    });
  });
});

describe("ModelEditor and the shared draft", () => {
  it("keeps an edit across a reload, with the badge", async () => {
    const first = renderPage();
    const note = await screen.findByDisplayValue("each day is staffed");
    fireEvent.change(note, { target: { value: "each day has enough people" } });
    expect(screen.getByText(/^Unpublished changes · edited \d{2}:\d{2}$/)).toBeInTheDocument();
    first.unmount();
    renderPage();
    expect(await screen.findByDisplayValue("each day has enough people")).toBeInTheDocument();
  });

  it("never swaps a draft from another version silently", async () => {
    localStorage.setItem("solver_model_draft_1", JSON.stringify({
      problemId: 1, base: "version-21", baseVersion: 1, editedAt: "2026-09-24T12:00:00Z", persisted: true,
      ir: { ...IR_V2, constraints: [] },
    }));
    renderPage();
    expect(await screen.findByText(/unpublished changes started from version 1/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start again from version 2/i }));
    expect(await screen.findByDisplayValue("c_cover")).toBeInTheDocument();
    expect(localStorage.getItem("solver_model_draft_1")).toBeNull();
  });

  it("clears the draft on publish, and on a confirmed discard only", async () => {
    const write = vi.fn().mockResolvedValue({ id: 23, version: 3 });
    stub({ write });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("each day is staffed"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(localStorage.getItem("solver_model_draft_1")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(write).toHaveBeenCalled());
    await waitFor(() => expect(localStorage.getItem("solver_model_draft_1")).toBeNull());
  });

  it("says when changes cannot outlive the page", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("each day is staffed"), { target: { value: "y" } });
    expect(screen.getByText(/not saved in this browser: they are lost on reload/i)).toBeInTheDocument();
  });
});

describe("ModelEditor's Blocks tab", () => {
  it("edits the same draft the forms edit, both ways", async () => {
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("each day is staffed"), { target: { value: "changed in forms" } });
    fireEvent.click(screen.getByRole("tab", { name: "Blocks" }));
    expect(screen.getByTestId("blocks-ir").textContent).toContain("changed in forms");
    fireEvent.click(screen.getByRole("button", { name: "edit in blocks" }));
    fireEvent.click(screen.getByRole("tab", { name: "Forms" }));
    expect(await screen.findByDisplayValue("changed in blocks")).toBeInTheDocument();
  });

  it("holds Publish while a block sits outside the model, and says so", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Blocks" }));
    fireEvent.click(screen.getByRole("button", { name: "drop a block beside the model" }));
    const publish = screen.getByRole("button", { name: /publish a new version/i });
    expect(publish).toBeDisabled();
    expect(publish).toHaveAttribute("title", "1 block is outside the model: put it inside, or delete it");
  });

  it("says the forms are the accessible way to edit", async () => {
    renderPage();
    expect(await screen.findByText(/the forms are the keyboard and screen-reader way to edit it/i)).toBeInTheDocument();
  });
});

describe("the domain's check of the draft (Blocks 4)", () => {
  it("a refusal only the domain can make, from the validate route, holds Publish and is shown", async () => {
    const { ApiError } = await import("../api/client");
    stub({
      write: (path: string) =>
        path.endsWith("/versions/validate")
          ? Promise.reject(new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "ir", "sets", 1], msg: "the domain has no entity type 'day'" }] })))
          : Promise.resolve({ id: 23, version: 3 }),
    });
    renderPage();
    const publish = await screen.findByRole("button", { name: /publish a new version/i });
    expect(await screen.findByText("the domain has no entity type 'day'", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(publish).toBeDisabled();
    expect(publish).toHaveAttribute("title", "the domain has no entity type 'day'");
  });

  it("asks the server only about a draft the shape rules accept", async () => {
    renderPage();
    await screen.findByRole("button", { name: /publish a new version/i });
    await waitFor(() =>
      expect(mockFetch.mock.calls.some(([path]) => String(path).endsWith("/versions/validate"))).toBe(true), { timeout: 3000 }
    );
  });
});

describe("a rule's chance in the forms (queue R8)", () => {
  it("writes the percentage as an epsilon, and a preferred rule drops it", async () => {
    renderPage();
    const field = await screen.findByLabelText(/May fail in at most this % of sampled futures/i);
    fireEvent.change(field, { target: { value: "10" } });
    await waitFor(() => {
      const draft = JSON.parse(localStorage.getItem("solver_model_draft_1") ?? "{}");
      expect(draft.ir.constraints[0].chance).toEqual({ epsilon: 0.1 });
    });
    fireEvent.change(field, { target: { value: "100" } });
    expect(screen.getByText("A share of futures is more than 0% and less than 100%.")).toBeInTheDocument();
    const strength = screen.getAllByLabelText("Strength")[0];
    fireEvent.change(strength, { target: { value: "soft" } });
    await waitFor(() => {
      const draft = JSON.parse(localStorage.getItem("solver_model_draft_1") ?? "{}");
      expect(draft.ir.constraints[0]).not.toHaveProperty("chance");
    });
  });
});
