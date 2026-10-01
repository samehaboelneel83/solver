import { describe, expect, it } from "vitest";
import { naturalOrder } from "./naturalOrder";

describe("members in reading order (UX audit C-4)", () => {
  it("puts numbers in number order when the order was only the keys as text", () => {
    expect(naturalOrder(["c1", "c10", "c11", "c2", "c20", "c3"])).toEqual(["c1", "c2", "c3", "c10", "c11", "c20"]);
  });
  it("keeps an order someone chose", () => {
    expect(naturalOrder(["mon", "tue", "wed"])).toEqual(["mon", "tue", "wed"]);
    expect(naturalOrder(["c3", "c1", "c2"])).toEqual(["c3", "c1", "c2"]);
  });
});
