import { describe, expect, it } from "vitest";
import { fromDatetimeLocalValue, toDatetimeLocalValue } from "./datetime";

describe("toDatetimeLocalValue", () => {
  it("renders an ISO UTC instant as the local wall-clock YYYY-MM-DDTHH:mm the browser would display", () => {
    const iso = "2026-10-01T08:00:00Z";
    // Timezone-safe expectation: computed via Date, not a hardcoded string,
    // so this passes regardless of the machine's local timezone.
    const date = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    const expected = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
      date.getHours()
    )}:${pad(date.getMinutes())}`;

    expect(toDatetimeLocalValue(iso)).toBe(expected);
  });

  it("returns the original string unchanged when it doesn't parse as a date", () => {
    expect(toDatetimeLocalValue("not-a-date")).toBe("not-a-date");
  });

  it("returns an empty string as-is", () => {
    // new Date("") is Invalid Date, so this must hit the NaN guard, not throw.
    expect(toDatetimeLocalValue("")).toBe("");
  });
});

describe("fromDatetimeLocalValue", () => {
  it("computes the same UTC instant the browser would for that local wall-clock string", () => {
    // Timezone-safe expectation: computed via `new Date(local).toISOString()`
    // directly, the same primitive the implementation itself uses -- this
    // asserts the function is exactly that conversion, not a guess at what
    // the offset should be.
    const local = "2026-03-15T14:45";
    const expected = new Date(local).toISOString();

    expect(fromDatetimeLocalValue(local)).toBe(expected);
  });

  it("round-trips back to the same local string via toDatetimeLocalValue", () => {
    const local = "2026-10-01T08:30";
    const iso = fromDatetimeLocalValue(local);

    expect(toDatetimeLocalValue(iso)).toBe(local);
  });

  it("produces a real ISO 8601 UTC string ending in Z", () => {
    const iso = fromDatetimeLocalValue("2026-01-01T00:00");
    expect(iso).toMatch(/Z$/);
    expect(new Date(iso).toISOString()).toBe(iso);
  });
});
