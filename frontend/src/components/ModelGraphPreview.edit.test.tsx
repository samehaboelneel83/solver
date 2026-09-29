/** Editing a model from its graph (Epic UX, U-2): inspectors, connections, deletion, keyboard. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { EMPTY_MODEL, withFormDraft, type FormDraft } from "../model/draftIr";
import ModelGraphPreview from "./ModelGraphPreview";

vi.mock("./modelStyles/FlowView", () => ({
  default: ({ onConnect }: { onConnect?: (source: string, target: string) => void }) => (
    <div>
      <span>Canvas</span>
      {onConnect && <button onClick={() => onConnect("model-set-shift", "model-var-extra")}>Drag shift to extra</button>}
      {onConnect && <button onClick={() => onConnect("model-par-demand", "model-objective")}>Drag demand to goal</button>}
      {onConnect && <button onClick={() => onConnect("model-var-staff", "model-con-cover")}>Drag staff to cover</button>}
    </div>
  ),
}));

function start(): FormDraft {
  return {
    sets: ["shift"],
    parameters: { demand: { index: ["shift"] } },
    variables: {
      staff: { domain: "integer", index: ["shift"], lower: 0, upper: 20 },
      bonus: { domain: "continuous", index: [] },
      extra: { domain: "continuous", index: [] },
    },
    constraints: [
      { id: "cover", forall: [{ index: "s", set: "shift" }], severity: "hard", relation: ">=",
        left: { var: "staff", index: ["s"] }, right: { par: "demand", index: ["s"] } },
      { id: "cap", severity: "hard", relation: "<=", left: { var: "bonus", index: [] }, right: { const: 100 } },
    ],
    objective: { sense: "minimize", mode: "weighted", terms: [
      { id: "wages", weight: 1, expression: { sum: { var: "staff", index: ["s"] }, over: [{ index: "s", set: "shift" }] } },
    ] },
  };
}

let latest: FormDraft;
function Editor() {
  const [draft, setDraft] = useState(start);
  latest = draft;
  return <ModelGraphPreview ir={withFormDraft({ ...EMPTY_MODEL }, draft)} entityTypes={[]} draft={draft}
    onEdit={(edit) => setDraft((current) => edit(current))} />;
}

const part = (name: RegExp) => within(screen.getByRole("list")).getByRole("button", { name });

it("edits a decision's bounds and name from its inspector, and every reference follows the rename", async () => {
  render(<Editor />);
  await screen.findByText("Canvas");
  fireEvent.click(part(/^staff/));
  const inspector = screen.getByRole("region", { name: /Inspector: staff/ });
  fireEvent.change(within(inspector).getByLabelText("Maximum"), { target: { value: "12" } });
  fireEvent.click(within(inspector).getByRole("button", { name: "Save bounds" }));
  expect(latest.variables.staff.upper).toBe(12);
  fireEvent.change(within(inspector).getByLabelText("Name"), { target: { value: "nurses" } });
  fireEvent.click(within(inspector).getByRole("button", { name: "Rename" }));
  expect(latest.variables.nurses).toBeDefined();
  expect(JSON.stringify(latest.constraints)).toContain('"var":"nurses"');
  expect(JSON.stringify(latest.objective)).toContain('"var":"nurses"');
  expect(screen.getByRole("status")).toHaveTextContent("every reference follows");
});

it("connects by keyboard: C on a part lists only what it can connect to", async () => {
  render(<Editor />);
  await screen.findByText("Canvas");
  fireEvent.keyDown(part(/^staff/), { key: "c" });
  const target = screen.getByLabelText("Connect staff to");
  const options = within(target).getAllByRole("option").map((o) => o.textContent);
  // Rules and the goal only: nothing flows from a decision into a set, a parameter or another decision.
  expect(options.slice(0, 2)).toEqual(["Rule cover", "Rule cap"]);
  expect(options).toHaveLength(3);
  expect(options[2]).toMatch(/^Goal/);
  fireEvent.change(target, { target: { value: "model-con-cap" } });
  fireEvent.change(screen.getByLabelText("Coefficient"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(latest.constraints[1].left).toEqual({ add: [{ var: "bonus", index: [] },
    { sum: { mul: [{ const: 3 }, { var: "staff", index: ["s"] }] }, over: [{ index: "s", set: "shift" }] }] });
});

it("connects by dragging, and says why a drag that means nothing is refused", async () => {
  render(<Editor />);
  fireEvent.click(await screen.findByRole("button", { name: "Drag shift to extra" }));
  expect(latest.variables.extra.index).toEqual(["shift"]);
  expect(screen.getByRole("status")).toHaveTextContent("Connected: extra gets one value for each shift.");
  fireEvent.click(screen.getByRole("button", { name: "Drag demand to goal" }));
  expect(screen.getByRole("status")).toHaveTextContent("Not connected: demand is data");
});

it("deletes by keyboard, showing first what goes with it, and leaves everything else as it was", async () => {
  render(<Editor />);
  await screen.findByText("Canvas");
  const before = start();
  fireEvent.keyDown(part(/^bonus/), { key: "Delete" });
  expect(screen.getByText(/These go with it, since they cannot stand without it: cap/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(latest.variables.bonus).toBeUndefined();
  expect(latest.constraints).toEqual([before.constraints[0]]);
  expect(latest.objective).toEqual(before.objective);
});

it("refuses to delete a set that indexes something, and says what", async () => {
  render(<Editor />);
  await screen.findByText("Canvas");
  fireEvent.keyDown(part(/^shift/), { key: "Delete" });
  expect(screen.getByRole("alert")).toHaveTextContent("staff, demand are indexed by shift");
  expect(latest).toEqual(start());
});
