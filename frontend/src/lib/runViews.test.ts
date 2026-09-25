import { describe, expect, it } from "vitest";
import { cellKey, defaultAxes, formatAmount, gridOf, membersOf, shade, viewsFor, type Shape } from "./runViews";

const shape = (sets: string[], kind: string, roles: Record<string, string> = {}, hasAmounts = true): Shape =>
  ({ sets, kind, roles, hasAmounts });

describe("which view draws a decision (queue R17)", () => {
  it("draws a weekly rota as a grid: time across, the slot down, the people inside", () => {
    const rota = shape(["employee", "day", "shift"], "binary", { employee: "agent", day: "time", shift: "time" });
    expect(viewsFor(rota)).toEqual(["grid", "list"]);
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
    expect(viewsFor(shape(["job", "machine"], "interval"))).toEqual(["list"]);
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
