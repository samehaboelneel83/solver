import { describe, expect, it } from "vitest";
import { resolveById } from "./selection";

describe("resolveById", () => {
  const items = [
    { id: 1, name: "A" },
    { id: 2, name: "B" },
  ];

  it("defaults to the first item when nothing was requested", () => {
    expect(resolveById(items, null, (row) => row.id)).toEqual({ item: items[0], missing: false });
  });

  it("returns the matching item when the id is present", () => {
    expect(resolveById(items, 2, (row) => row.id)).toEqual({ item: items[1], missing: false });
  });

  it("does not substitute another item when the explicit id is missing", () => {
    expect(resolveById(items, 99, (row) => row.id)).toEqual({ item: null, missing: true });
  });
});
