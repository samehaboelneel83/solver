import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BlocklyEdit from "./BlocklyEdit";
import { ToastProvider } from "../ToastProvider";
import { clearDraft, readDraft, writeDraft } from "../../model/draftStore";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

// Blockly cannot draw in jsdom; the editor is a stand-in, as in the Model
// editor's tests. These are about the pane: the draft it edits, and Publish.
vi.mock("../BlocksEditor", () => ({
  default: ({ ir, onChange }: { ir: Record<string, unknown>; onChange: (ir: Record<string, unknown>, paths: Map<string, unknown>, outside: number) => void }) => (
    <div data-testid="blocks-editor">
      <span data-testid="blocks-ir">{JSON.stringify(ir)}</span>
      <button type="button" onClick={() => onChange({ ...ir, objective: { sense: "maximize", terms: [] } }, new Map(), 0)}>
        edit in blocks
      </button>
      <button type="button" onClick={() => onChange(ir, new Map(), 2)}>drop two blocks beside the model</button>
      <button type="button" onClick={() => onChange({ ...ir, constraints: [{ id: "c", left: { const: null }, relation: "<=", right: { const: 1 }, severity: "hard" }] }, new Map(), 0)}>
        leave a socket empty
      </button>
    </div>
  ),
}));

const { apiFetch } = await import("../../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const IR = {
  version: 2,
  sets: ["feed"],
  parameters: {},
  variables: { use: { index: ["feed"], domain: "continuous", lower: 0, upper: 100 } },
  constraints: [],
  objective: { sense: "minimize", terms: [] },
};

function stub() {
  mockFetch.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method === "POST" && path === "/api/v1/problems/7/versions") return Promise.resolve({ id: 71, version: 4 });
    if (path.startsWith("/api/v1/entity-types")) {
      return Promise.resolve({ items: [{ id: 1, domain_id: 1, name: "feed", role: "resource", colour: null, attributes: [] }], total: 1 });
    }
    if (path.startsWith("/api/v1/parameters")) return Promise.resolve({ items: [], total: 0 });
    if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve({ items: [], total: 0 });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function renderPane(props: Partial<Parameters<typeof BlocklyEdit>[0]> = {}) {
  const onVersion = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <BlocklyEdit domainId={1} problemId={7} versionId={70} versionNumber={3} ir={IR} onVersion={onVersion} {...props} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
  return { onVersion };
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  clearDraft(7);
  stub();
});

describe("the optimization view's Edit mode", () => {
  it("shows the version on screen until something is edited, and writes nothing by opening", async () => {
    renderPane();
    expect(JSON.parse((await screen.findByTestId("blocks-ir")).textContent!)).toEqual(IR);
    expect(readDraft(7)).toBeNull();
  });

  it("an edit writes the shared draft, seeded from the version on screen", async () => {
    renderPane();
    fireEvent.click(await screen.findByRole("button", { name: "edit in blocks" }));
    const draft = readDraft(7)!;
    expect(draft.base).toBe("version-70");
    expect(draft.baseVersion).toBe(3);
    expect((draft.ir.objective as { sense: string }).sense).toBe("maximize");
    expect(screen.getByText(/^Unpublished changes · edited/)).toBeInTheDocument();
  });

  it("continues a draft the Model editor started from the same version", async () => {
    writeDraft({ problemId: 7, base: "version-70", baseVersion: 3, ir: { ...IR, sets: ["feed", "from_forms"] } });
    renderPane();
    expect((await screen.findByTestId("blocks-ir")).textContent).toContain("from_forms");
  });

  it("never swaps a draft from another version in silently: it asks", async () => {
    writeDraft({ problemId: 7, base: "version-69", baseVersion: 2, ir: IR });
    const { onVersion } = renderPane();
    expect(await screen.findByText(/unpublished changes started from version 2/i)).toBeInTheDocument();
    expect(screen.queryByTestId("blocks-editor")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue the draft" }));
    expect(onVersion).toHaveBeenCalledWith(69);
  });

  it("holds Publish while blocks sit outside the model, or a socket is empty, and says why", async () => {
    renderPane();
    fireEvent.click(await screen.findByRole("button", { name: "drop two blocks beside the model" }));
    const publish = screen.getByRole("button", { name: /publish a new version/i });
    expect(publish).toBeDisabled();
    expect(publish).toHaveAttribute("title", "2 blocks are outside the model: put them inside, or delete them");
    fireEvent.click(screen.getByRole("button", { name: "leave a socket empty" }));
    expect(await screen.findByText("null is not a number")).toBeInTheDocument();
    expect(publish).toBeDisabled();
    expect(publish).toHaveAttribute("title", "null is not a number");
  });

  it("publishes the draft as a new version, clears it, and moves the view to that version", async () => {
    const { onVersion } = renderPane();
    fireEvent.click(await screen.findByRole("button", { name: "edit in blocks" }));
    fireEvent.click(screen.getByRole("button", { name: /publish a new version/i }));
    await waitFor(() => expect(onVersion).toHaveBeenCalledWith(71));
    const post = mockFetch.mock.calls.find(([path, options]) => path === "/api/v1/problems/7/versions" && options?.method === "POST");
    // What the blocks made, as the contract wants it: a goal with no terms is omitted.
    const sent = JSON.parse(post![1].body).ir;
    expect(sent.variables).toEqual(IR.variables);
    expect(sent).not.toHaveProperty("objective");
    expect(readDraft(7)).toBeNull();
  });

  it("a problem with no model yet starts from an empty one", async () => {
    renderPane({ versionId: null, versionNumber: null, ir: null });
    const shown = JSON.parse((await screen.findByTestId("blocks-ir")).textContent!);
    expect(shown.constraints).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "edit in blocks" }));
    expect(readDraft(7)!.base).toBe("scratch");
  });

  it("says the forms are the accessible way to edit", async () => {
    renderPane();
    expect(await screen.findByText(/keyboard and screen-reader way to edit it/i)).toBeInTheDocument();
  });
});
