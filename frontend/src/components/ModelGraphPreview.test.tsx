import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
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
