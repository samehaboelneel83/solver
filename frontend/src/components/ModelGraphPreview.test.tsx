import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { setToken } from "../api/client";
import ModelGraphPreview from "./ModelGraphPreview";
vi.mock("./modelStyles/FlowView", () => ({ default: ({ positions, onMove, nudge }: {
  positions: Record<string, { x: number; y: number }>;
  onMove: (id: string, position: { x: number; y: number }) => void;
  nudge?: { id: string; dx: number; dy: number; seq: number } | null;
}) => <div><span>Canvas</span><output data-testid="layout">{JSON.stringify(positions)}</output>
  <output data-testid="nudge">{JSON.stringify(nudge ?? null)}</output>
  <button onClick={() => onMove("model-var-staff", { x: 125, y: 90 })}>Move staff card</button></div> }));

it("offers the matching shared editor after keyboard-accessible selection", async () => {
  render(<ModelGraphPreview ir={{ sets: [], variables: { staff: { domain: "integer", lower: 0 } }, constraints: [], objective: { sense: "min", terms: [] } }} entityTypes={[]}
    editorHref={part => part === "objective" ? "#objective-editor" : "#declarations-editor"} />);
  await screen.findByText("Canvas");
  const button = screen.getAllByRole("button").find(item => item.textContent?.startsWith("staff"))!;
  fireEvent.click(button);
  expect(screen.getByRole("link", { name: "Edit declarations below" }).getAttribute("href")).toBe("#declarations-editor");
});

it("does not advertise editing in read-only consumers", async () => {
  render(<ModelGraphPreview ir={{ sets: [], variables: {}, constraints: [] }} entityTypes={[]} />);
  await screen.findByText("Canvas");
  expect(screen.queryByRole("link")).toBeNull();
});


it("keeps layout separate from model edits and resets it on request", async () => {
  const ir = { sets: [], variables: { staff: { domain: "integer", lower: 0 } }, constraints: [] };
  const { rerender } = render(<ModelGraphPreview ir={ir} entityTypes={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Move staff card" }));
  rerender(<ModelGraphPreview ir={{ ...ir, variables: { staff: { domain: "integer", lower: 2 } } }} entityTypes={[]} />);
  expect(await screen.findByTestId("layout")).toHaveTextContent('"x":125');
  expect(ir.variables.staff.lower).toBe(0);
  expect(ir).not.toHaveProperty("layout");
  fireEvent.click(screen.getByRole("button", { name: "Reset graph layout" }));
  expect(await screen.findByTestId("layout")).toHaveTextContent("{}");
});


const tokenFor = (sub: string) => `header.${btoa(JSON.stringify({ sub }))}.signature`;
const STAFF = { sets: [], variables: { staff: { domain: "integer", lower: 0 } }, constraints: [] };
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

it("keeps a problem's layout across a remount, per account and per problem", async () => {
  setToken(tokenFor("alice"));
  const first = render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Move staff card" }));
  first.unmount();

  const again = render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  expect(await screen.findByTestId("layout")).toHaveTextContent('"x":125');
  again.unmount();

  setToken(tokenFor("bob"));
  const bob = render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  expect(await screen.findByTestId("layout")).toHaveTextContent("{}");
  bob.unmount();

  setToken(tokenFor("alice"));
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-2" />);
  expect(await screen.findByTestId("layout")).toHaveTextContent("{}");
});

it("clears the kept layout on reset", async () => {
  setToken(tokenFor("alice"));
  const first = render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Move staff card" }));
  fireEvent.click(screen.getByRole("button", { name: "Reset graph layout" }));
  first.unmount();
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  expect(await screen.findByTestId("layout")).toHaveTextContent("{}");
});

it("says so when the browser cannot keep the layout", async () => {
  setToken(tokenFor("alice"));
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Move staff card" }));
  expect(screen.getByText(/could not save the card positions/)).toBeInTheDocument();
  expect(await screen.findByTestId("layout")).toHaveTextContent('"x":125');
});

it("moves the selected card without dragging, one step per press", async () => {
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} />);
  await screen.findByText("Canvas");
  expect(screen.queryByRole("group", { name: /^Move / })).toBeNull();
  fireEvent.click(screen.getAllByRole("button").find(item => item.textContent?.startsWith("staff"))!);
  const right = screen.getByRole("button", { name: /^Move staff.* right$/ });
  fireEvent.click(right);
  expect(JSON.parse(screen.getByTestId("nudge").textContent!)).toEqual({ id: "model-var-staff", dx: 40, dy: 0, seq: 1 });
  fireEvent.click(right);
  expect(JSON.parse(screen.getByTestId("nudge").textContent!)).toMatchObject({ dx: 40, seq: 2 });
  fireEvent.click(screen.getByRole("button", { name: /^Move staff.* up$/ }));
  expect(JSON.parse(screen.getByTestId("nudge").textContent!)).toMatchObject({ dx: 0, dy: -40, seq: 3 });
});

function serverLayout(kept: Record<string, { x: number; y: number }>) {
  const calls: { method: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_path, init) => {
    const method = init?.method ?? "GET";
    calls.push({ method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const positions = method === "PUT" ? JSON.parse(String(init?.body)).positions : kept;
    return new Response(JSON.stringify({ positions, updated_at: null }), { status: 200 });
  });
  return calls;
}

it("takes the server's layout, so it follows the person to another browser", async () => {
  setToken(tokenFor("alice"));
  serverLayout({ "model-var-staff": { x: 300, y: 40 } });
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-5" layoutProblemId={5} />);
  await waitFor(() => expect(screen.getByTestId("layout")).toHaveTextContent('"x":300'));
  expect(screen.getByText(/kept for you on the server/)).toBeInTheDocument();
});

it("saves a move to the server after a pause, and hands over a layout this browser kept", async () => {
  setToken(tokenFor("alice"));
  localStorage.clear();
  const first = render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-6" />);
  fireEvent.click(await screen.findByRole("button", { name: "Move staff card" }));
  first.unmount();

  const calls = serverLayout({});
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-6" layoutProblemId={6} />);
  // The server had none: this browser's layout is handed over once.
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
  expect(calls[1].body).toEqual({ positions: { "model-var-staff": { x: 125, y: 90 } } });
  fireEvent.click(screen.getByRole("button", { name: "Reset graph layout" }));
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2), { timeout: 2000 });
  expect(calls.at(-1)?.body).toEqual({ positions: {} });
});

it("says so when the server cannot keep the layout", async () => {
  setToken(tokenFor("alice"));
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
  render(<ModelGraphPreview ir={STAFF} entityTypes={[]} layoutKey="problem-7" layoutProblemId={7} />);
  expect(await screen.findByText(/server could not keep the card positions/)).toBeInTheDocument();
});
