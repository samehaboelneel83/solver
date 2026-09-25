import { describe, expect, it } from "vitest";
import {
  cellKey,
  defaultAxes,
  formatAmount,
  ganttBars,
  mapMarks,
  gridOf,
  membersOf,
  rowPosition,
  shade,
  timelineBars,
  viewsFor,
  type Shape,
} from "./runViews";

const shape = (sets: string[], kind: string, roles: Record<string, string> = {}, hasAmounts = true): Shape =>
  ({ sets, kind, roles, hasAmounts });

describe("which view draws a decision (queue R17)", () => {
  it("draws a weekly rota as a grid: time across, the slot down, the people inside", () => {
    const rota = shape(["employee", "day", "shift"], "binary", { employee: "agent", day: "time", shift: "time" });
    expect(viewsFor(rota)).toEqual(["grid", "timeline", "list"]);
    // day is the first time set: across; shift down; employees inside each cell.
    expect(defaultAxes(rota)).toEqual({ rows: 2, cols: 1, inside: [0] });
  });

  it("chooses by kind and number of sets", () => {
    expect(viewsFor(shape(["item"], "binary"))).toEqual(["chosen", "list"]);
    expect(viewsFor(shape(["site", "customer"], "binary"))).toEqual(["grid", "list"]);
    expect(viewsFor(shape(["person"], "continuous"))).toEqual(["bars", "line", "list"]);
    expect(viewsFor(shape(["day"], "integer", { day: "time" }))).toEqual(["line", "bars", "list"]);
    expect(viewsFor(shape(["plant", "customer"], "continuous"))).toEqual(["heat", "grid", "list"]);
    expect(viewsFor(shape(["product", "plant", "week"], "integer"))).toEqual(["panels", "heat", "grid", "list"]);
    expect(viewsFor(shape([], "integer"))).toEqual(["value", "list"]);
  });

  it("falls back to the list where nothing better can be drawn", () => {
    expect(viewsFor(shape(["plant", "day"], "integer", {}, false))).toEqual(["list"]);
    expect(viewsFor(shape(["job", "machine"], "interval", {}, false))).toEqual(["list"]);
  });

  it("puts the second set across and the first down when no role says otherwise", () => {
    expect(defaultAxes(shape(["plant", "customer"], "continuous"))).toEqual({ rows: 0, cols: 1, inside: [] });
    expect(defaultAxes(shape(["product", "plant", "week"], "integer", { week: "time" }))).toEqual({ rows: 0, cols: 2, inside: [1] });
  });
});

describe("laying out a grid", () => {
  it("keeps the dataset's order, then adds members met only in the answer", () => {
    expect(membersOf("day", { day: ["mon", "tue", "wed"] }, ["wed", "sun", "mon"])).toEqual(["mon", "tue", "wed", "sun"]);
  });

  it("puts each tuple's remaining positions inside its cell, and sums amounts", () => {
    const cells = gridOf(
      [
        { index: ["ahmed", "mon", "early"], value: null },
        { index: ["mona", "mon", "early"], value: null },
        { index: ["ahmed", "tue", "late"], value: null },
      ],
      { rows: 2, cols: 1, inside: [0] },
    );
    expect(cells.get(cellKey("early", "mon"))!.inside).toEqual([["ahmed"], ["mona"]]);
    expect(cells.get(cellKey("late", "tue"))!.inside).toEqual([["ahmed"]]);
    const summed = gridOf([{ index: ["a", "x", "w1"], value: 2 }, { index: ["a", "x", "w2"], value: 3.5 }], { rows: 0, cols: 1, inside: [2] });
    expect(summed.get(cellKey("a", "x"))!.value).toBe(5.5);
  });

  it("shades by magnitude and reads numbers plainly", () => {
    expect(shade(5, 10)).toBe(0.5);
    expect(shade(null, 10)).toBe(0);
    expect(formatAmount(1200)).toBe("1,200");
    expect(formatAmount(3.14159)).toBe("3.14");
  });
});

describe("Gantt and timeline (queue R17b)", () => {
  it("draws an interval from its start and end amounts, one row per machine", () => {
    const jobs = shape(["job", "machine"], "interval", { machine: "resource" });
    expect(viewsFor(jobs)).toEqual(["gantt", "list"]);
    expect(rowPosition(jobs)).toBe(1);
    const bars = ganttBars(
      [{ index: ["j2", "m1"], value: 3 }],
      [{ index: ["j1", "m1"], value: 3 }, { index: ["j2", "m1"], value: 7 }],
      null,
      1,
    );
    // j1 starts at 0: an amount the answer does not list is 0.
    expect(bars).toEqual([
      { row: "m1", label: ["j1"], start: 0, end: 3 },
      { row: "m1", label: ["j2"], start: 3, end: 7 },
    ]);
  });

  it("keeps only the present instances of an optional interval", () => {
    const bars = ganttBars([], [{ index: ["a"], value: 2 }, { index: ["b"], value: 5 }], [["b"]], 0);
    expect(bars.map((b) => b.row)).toEqual(["b"]);
  });

  it("merges consecutive chosen days into one bar per person, in the week's own order", () => {
    const week = ["mon", "tue", "wed", "thu", "fri"];
    const bars = timelineBars([["ana", "mon"], ["ana", "tue"], ["ana", "thu"], ["ben", "wed"]], 1, 0, week);
    expect(bars).toEqual([
      { row: "ana", label: [], start: 0, end: 2 },
      { row: "ana", label: [], start: 3, end: 4 },
      { row: "ben", label: [], start: 2, end: 3 },
    ]);
  });
});

describe("an answer on a map (queue R17b)", () => {
  const places = { site: { n: [31, 30] as [number, number], s: [31, 29] as [number, number] },
                   customer: { c1: [32, 30] as [number, number] } };

  it("offers the map second over any located set", () => {
    expect(viewsFor({ sets: ["site"], kind: "binary", roles: {}, hasAmounts: true, located: ["site"] })).toEqual(["chosen", "map", "list"]);
    expect(viewsFor({ sets: ["site"], kind: "binary", roles: {}, hasAmounts: true, located: [] })).toEqual(["chosen", "list"]);
  });

  it("marks the chosen sites and draws a line for each site serving a customer", () => {
    const one = mapMarks(["site"], [{ index: ["n"], value: null }], places);
    expect(one.points.map((p) => [p.key, p.chosen])).toEqual([["n", true], ["s", false]]);
    const two = mapMarks(["site", "customer"], [{ index: ["s", "c1"], value: 4 }], places);
    expect(two.lines).toEqual([{ from: [31, 29], to: [32, 30], value: 4, group: "", label: "s → c1" }]);
  });

  it("colours a route's legs by vehicle: the rest of the index is the group", () => {
    const stops = { stop: { a: [0, 0] as [number, number], b: [1, 0] as [number, number] } };
    const legs = mapMarks(["vehicle", "stop", "stop"], [{ index: ["v1", "a", "b"], value: null }], stops);
    expect(legs.lines.map((l) => [l.group, l.label])).toEqual([["v1", "a → b"]]);
  });
});
