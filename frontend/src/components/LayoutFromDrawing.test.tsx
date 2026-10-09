import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { LayoutFromDrawing } from "./LayoutFromDrawing";

const DRAWING = { upload_id: "u1", filename: "camp.dxf", local_metres: true, notes: [], layers: [
  { name: "BOUNDARY", features: 30, kinds: { polygon: 30 } }, { name: "OBSTACLES", features: 5, kinds: { polygon: 5 } },
  { name: "DOORS", features: 68, kinds: { line: 68 } }, { name: "LABELS", features: 30, kinds: { text: 30 } }] };
const PREVIEW = { form: "generated", grid_step_m: 0.5, aisle_m: { asked: 0.35, modelled: 0.5, cells: 1, side: "any" },
  areas: 30, zones: ["C01"], free_area_m2: 4210.5, candidates: 54468, candidates_by_kind: { bed: 54468 },
  upper_bound: { items: 2581, how: "free area / each item's share" }, access: null, not_modelled: "Nothing." };

function mount(onMade = vi.fn()) {
  render(<QueryClientProvider client={new QueryClient()}><LayoutFromDrawing domainId={7} name="Camp beds" onMade={onMade} /></QueryClientProvider>);
  return onMade;
}

describe("laying items out on a drawing, without the Assistant", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path, init) => {
      const p = String(path);
      if (p === "/api/v1/layouts/drawings") return DRAWING;
      if (p === "/api/v1/layouts/preview") return PREVIEW;
      if (p === "/api/v1/layouts/build") {
        const body = JSON.parse(String((init as RequestInit).body));
        return body.dry_run ? { trial: { status: "feasible", objective: 2290 } } : { problem_id: 41, scenario_id: 90 };
      }
      throw new Error(`unexpected ${p}`);
    });
  });

  it("reads the layers, previews the layout and makes the problem", async () => {
    const onMade = mount();
    fireEvent.change(screen.getByLabelText(/The drawing/), { target: { files: [new File(["x"], "camp.dxf")] } });
    const areas = await screen.findByRole("group", { name: "Where items may go" });
    expect(within(areas).getByLabelText(/BOUNDARY/)).toBeChecked(); // the polygon layer, as a visible guess
    fireEvent.click(within(screen.getByRole("group", { name: "What no item may cover" })).getByLabelText(/OBSTACLES/));
    fireEvent.click(within(screen.getByRole("group", { name: "Every item must be reachable from" })).getByLabelText(/DOORS/));
    fireEvent.change(screen.getByLabelText("Names of the areas (a text layer, optional)"), { target: { value: "LABELS" } });
    fireEvent.change(screen.getByLabelText("Item 1 name"), { target: { value: "bed" } });
    fireEvent.change(screen.getByLabelText("Item 1 length"), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText("Item 1 width"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText(/Aisle beside each item/), { target: { value: "0.35" } });
    fireEvent.click(screen.getByLabelText(/Every position listed/));
    fireEvent.click(screen.getByRole("button", { name: "Preview the layout" }));
    const shown = await screen.findByRole("region", { name: "Layout preview" });
    expect(shown).toHaveTextContent("54,468 candidate positions");
    expect(shown).toHaveTextContent("At most 2,581 items fit");
    const sent = JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p]) => p === "/api/v1/layouts/preview")![1] as RequestInit).body));
    expect(sent).toEqual({ upload_id: "u1", area_layers: ["BOUNDARY"], blocked_layers: ["OBSTACLES"], access_layers: ["DOORS"],
      label_layer: "LABELS", items: [{ name: "bed", length: 1.5, width: 0.5, rotations: [0, 90], value: 1 }],
      aisle: 0.35, aisle_side: "any", form: "candidates" });
    fireEvent.click(screen.getByRole("button", { name: "Check with a short trial solve" }));
    expect(await screen.findByText(/Trial solve: feasible, 2,290 items/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make “Camp beds”" }));
    await waitFor(() => expect(onMade).toHaveBeenCalledWith(41));
    const made = vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/api/v1/layouts/build").map(([, i]) => JSON.parse(String((i as RequestInit).body)));
    expect(made[1]).toMatchObject({ domain_id: 7, problem_name: "Camp beds", form: "candidates" });
    expect(made[1].dry_run).toBeUndefined();
  });
});
