import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";
import ServerDraftSync, { AUTOSAVE_MS } from "./ServerDraftSync";
import { clearDraft, readDraft, readServerLink, writeDraft, writeServerLink, type ModelDraft } from "./draftStore";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const P = 71;
const server = (revision: number, ir: Record<string, unknown> = { sets: ["server"] }) => ({
  id: 5, problem_id: P, base_version_id: 22, base_version: 2, ir, revision,
  created_at: "2026-09-28T10:00:00Z", updated_at: "2026-09-28T11:00:00Z",
});
const STALE = new ApiError(409, JSON.stringify({ detail: "This draft was changed by someone else after this form loaded it." }));

beforeEach(() => mockFetch.mockReset());
afterEach(() => { clearDraft(P); localStorage.clear(); });

it("offers a server draft to a browser that has none", async () => {
  mockFetch.mockResolvedValueOnce(server(3));
  render(<ServerDraftSync problemId={P} draft={null} disabled={false} />);
  expect(await screen.findByText(/You have a draft saved to the server \(revision 3/)).toBeInTheDocument();
  expect(screen.getByText(/started from version 2/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open the server draft" }));
  expect(readDraft(P)).toMatchObject({ base: "version-22", baseVersion: 2, ir: { sets: ["server"] } });
  expect(readServerLink(P)?.revision).toBe(3);
});

it("shows nothing when there is no server draft and no local one", async () => {
  mockFetch.mockRejectedValueOnce(new ApiError(404, "no draft"));
  const { container } = render(<ServerDraftSync problemId={P} draft={null} disabled={false} />);
  await waitFor(() => expect(mockFetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("saves a local draft naming the revision it was built on", async () => {
  const local = writeDraft({ problemId: P, base: "version-22", baseVersion: 2, ir: { sets: ["local"] } });
  mockFetch.mockRejectedValueOnce(new ApiError(404, "no draft"));
  const { rerender } = render(<ServerDraftSync problemId={P} draft={local} disabled={false} />);
  expect(screen.getByText("Saving to the server in a moment…")).toBeInTheDocument();
  mockFetch.mockResolvedValueOnce(server(1, local.ir));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save to server" })));
  const [path, options] = mockFetch.mock.calls.at(-1)!;
  expect(path).toBe(`/api/v1/problems/${P}/draft`);
  expect(JSON.parse(options.body)).toEqual({ ir: { sets: ["local"] }, base_version_id: 22, expected_revision: null });
  rerender(<ServerDraftSync problemId={P} draft={readDraft(P)} disabled={false} />);
  expect(screen.getByText("Saved to the server · revision 1")).toBeInTheDocument();

  const edited = writeDraft({ problemId: P, base: "version-22", baseVersion: 2, ir: { sets: ["edited"] } });
  rerender(<ServerDraftSync problemId={P} draft={edited} disabled={false} />);
  expect(screen.getByText("Saving to the server in a moment…")).toBeInTheDocument();
  mockFetch.mockResolvedValueOnce(server(2, edited.ir));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save to server" })));
  expect(JSON.parse(mockFetch.mock.calls.at(-1)![1].body).expected_revision).toBe(1);
});

it("saves a draft to the server by itself once the edits pause (UX audit B-6)", async () => {
  vi.useFakeTimers();
  try {
    const local = writeDraft({ problemId: P, base: "version-22", baseVersion: 2, ir: { sets: ["typed"] } });
    mockFetch.mockRejectedValueOnce(new ApiError(404, "no draft"));
    render(<ServerDraftSync problemId={P} draft={local} disabled={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    mockFetch.mockResolvedValueOnce(server(1, local.ir));
    await act(async () => { await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 10); });
    const [path, options] = mockFetch.mock.calls.at(-1)!;
    expect(path).toBe(`/api/v1/problems/${P}/draft`);
    expect(options.method).toBe("PUT");
    expect(screen.getByText("Saved to the server as revision 1.")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

async function staleSave(): Promise<ModelDraft> {
  const local = writeDraft({ problemId: P, base: "version-22", baseVersion: 2, ir: { sets: ["local"] } });
  writeServerLink(P, { revision: 1, savedEditedAt: "earlier" });
  mockFetch.mockResolvedValueOnce(server(1));
  render(<ServerDraftSync problemId={P} draft={local} disabled={false} />);
  await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
  mockFetch.mockRejectedValueOnce(STALE).mockResolvedValueOnce(server(4));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save to server" })));
  expect(await screen.findByRole("alert")).toHaveTextContent(/saved from another tab or browser \(revision 4/);
  return local;
}

it("asks which copy to keep when the server copy moved on, and can keep this one", async () => {
  await staleSave();
  mockFetch.mockResolvedValueOnce(server(5, { sets: ["local"] }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Keep this draft and replace the server copy" })));
  expect(JSON.parse(mockFetch.mock.calls.at(-1)![1].body)).toMatchObject({ ir: { sets: ["local"] }, expected_revision: 4 });
  expect(readServerLink(P)?.revision).toBe(5);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("can take the server copy instead", async () => {
  await staleSave();
  fireEvent.click(screen.getByRole("button", { name: "Use the server copy" }));
  expect(readDraft(P)?.ir).toEqual({ sets: ["server"] });
  expect(readServerLink(P)?.revision).toBe(4);
});

