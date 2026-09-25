import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run } from "../api/v1";
import RunViews from "./RunViews";

const base = {
  labels: { employee: { ahmed: "Ahmed", mona: "Mona" }, day: { mon: "Monday", tue: "Tuesday" } },
  set_roles: { employee: "agent", day: "time", shift: "time", plant: "location", customer: "location" },
  set_order: { day: ["mon", "tue"], shift: ["early", "late"], employee: ["ahmed", "mona"], plant: ["n", "s"], customer: ["c1", "c2"] },
} as const;

function run(extra: Partial<Run>): Run {
  return { ...base, index_sets: { variables: {}, constraints: {} }, assignments: {}, amounts: {}, variable_kinds: {}, ...extra } as unknown as Run;
}

describe("a run drawn by the shape of each decision (queue R17)", () => {
  it("draws a roster as a grid: days across, shifts down, the people inside each cell", () => {
    render(<RunViews run={run({
      index_sets: { variables: { assign: ["employee", "day", "shift"] }, constraints: {} },
      variable_kinds: { assign: "binary" },
      assignments: { assign: [["ahmed", "mon", "early"], ["mona", "mon", "early"], ["ahmed", "tue", "late"]] },
    })} />);
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["", "Monday", "Tuesday"]);
    expect(screen.getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["early", "late"]);
    const early = screen.getByRole("rowheader", { name: "early" }).closest("tr")!;
    expect(within(early).getByText("Ahmed")).toBeInTheDocument();
    expect(within(early).getByText("Mona")).toBeInTheDocument();
  });

  it("draws amounts over two sets as a heat matrix with their values, and lets the axes be swapped", () => {
    render(<RunViews run={run({
      index_sets: { variables: { ship: ["plant", "customer"] }, constraints: {} },
      variable_kinds: { ship: "continuous" },
      assignments: { ship: [["n", "c1"], ["s", "c2"]] },
      amounts: { ship: [{ index: ["n", "c1"], value: 40 }, { index: ["s", "c2"], value: 2.5 }] },
    })} />);
    expect(screen.getByRole("tab", { name: "Heat matrix", selected: true })).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["n", "s"]);
    fireEvent.change(screen.getByLabelText("Down"), { target: { value: "1" } });
    expect(screen.getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["c1", "c2"]);
  });

  it("marks the chosen members of a set, and keeps the list one click away", () => {
    render(<RunViews run={run({
      index_sets: { variables: { open: ["plant"] }, constraints: {} },
      variable_kinds: { open: "binary" },
      assignments: { open: [["s"]] },
    })} />);
    expect(screen.getByLabelText("s (chosen)")).toBeInTheDocument();
    expect(screen.getByLabelText("n")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "List" }));
    expect(screen.getByRole("listitem")).toHaveTextContent("s");
  });

  it("draws an amount over time as a line, and one over people as bars", () => {
    render(<RunViews run={run({
      index_sets: { variables: { stock: ["day"], hours: ["employee"] }, constraints: {} },
      variable_kinds: { stock: "integer", hours: "continuous" },
      assignments: { stock: [["mon"], ["tue"]], hours: [["ahmed"]] },
      amounts: { stock: [{ index: ["mon"], value: 5 }, { index: ["tue"], value: 9 }], hours: [{ index: ["ahmed"], value: 38.5 }] },
    })} />);
    expect(screen.getByRole("img", { name: "day over time" })).toBeInTheDocument();
    expect(screen.getByText("38.5")).toBeInTheDocument();
  });

  it("falls back to the list for a run recorded before amounts were kept", () => {
    render(<RunViews run={run({
      index_sets: { variables: { ship: ["plant", "customer"] }, constraints: {} },
      variable_kinds: { ship: "continuous" },
      assignments: { ship: [["n", "c1"]] },
      amounts: null,
    })} />);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByRole("listitem")).toHaveTextContent("n · c1");
  });
});
