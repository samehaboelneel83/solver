import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { setToken } from "../api/client";
import ModelGraphPreview from "./ModelGraphPreview";
vi.mock("./modelStyles/FlowView", () => ({ default: ({ positions, onMove }: {
  positions: Record<string, { x: number; y: number }>;
  onMove: (id: string, position: { x: number; y: number }) => void;
}) => <div><span>Canvas</span><output data-testid="layout">{JSON.stringify(positions)}</output>
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
