import { describe, expect, it } from "vitest";
import { formatCellValue } from "./format";

describe("formatCellValue", () => {
  it("renders a datetime via Intl.DateTimeFormat in local time and keeps the raw ISO value in `title` (E-3)", () => {
    const iso = "2026-09-17T12:37:36.120814Z";
    const result = formatCellValue({ type: "datetime" }, iso);

    // Computed with Date/Intl in the test itself, never a hard-coded string
    // or offset, so this passes under any reader time zone.
    const expectedText = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));

    expect(result.text).toBe(expectedText);
    expect(result.text).not.toContain(iso);
    expect(result.title).toBe(iso);
  });

  it("renders a date without a time component, keeping the raw value in `title`", () => {
    const iso = "2026-09-17";
    const result = formatCellValue({ type: "date" }, iso);

    const expectedText = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(2026, 8, 17)));

    expect(result.text).toBe(expectedText);
    expect(result.text).not.toMatch(/\d{1,2}:\d{2}/);
    expect(result.title).toBe(iso);
  });

  it("renders true/false as a check mark / dash with an accessible name, never the bare words (E-5)", () => {
    expect(formatCellValue({ type: "boolean" }, true)).toEqual({ text: "✓", ariaLabel: "Yes" });
    expect(formatCellValue({ type: "boolean" }, false)).toEqual({ text: "—", ariaLabel: "No" });
  });

  it("renders a uuid unchanged", () => {
    const id = "11111111-1111-1111-1111-111111111111";
    expect(formatCellValue({ type: "uuid" }, id)).toEqual({ text: id });
  });

  it("renders other types unchanged", () => {
    expect(formatCellValue({ type: "string" }, "hello")).toEqual({ text: "hello" });
    expect(formatCellValue({ type: "integer" }, 42)).toEqual({ text: "42" });
  });

  it("renders null/undefined/empty string as an empty cell", () => {
    expect(formatCellValue({ type: "string" }, null)).toEqual({ text: "" });
    expect(formatCellValue({ type: "string" }, undefined)).toEqual({ text: "" });
    expect(formatCellValue({ type: "string" }, "")).toEqual({ text: "" });
  });

  it("falls back to the unchanged value when a datetime/date string doesn't parse", () => {
    expect(formatCellValue({ type: "datetime" }, "not-a-date")).toEqual({ text: "not-a-date" });
    expect(formatCellValue({ type: "date" }, "also-not-a-date")).toEqual({ text: "also-not-a-date" });
  });

  it("json-stringifies plain object values", () => {
    expect(formatCellValue({ type: "json" }, { a: 1 })).toEqual({ text: '{"a":1}' });
  });
});

describe("a line in a record (benchmark, October 2026)", () => {
  it("is named as a shape, like a point or an area", async () => {
    const { shapeWords } = await import("../components/AttrsForm");
    expect(shapeWords({ type: "LineString", coordinates: [[31, 30], [31.1, 30], [31.2, 30.1]] })).toBe("Line of 3 points");
    expect(shapeWords({ type: "MultiLineString", coordinates: [[[31, 30], [31.1, 30]], [[31, 31], [31.1, 31]]] })).toBe("Line in 2 parts");
  });
});
