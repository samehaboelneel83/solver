import { describe, expect, it } from "vitest";
import { madeIn } from "./ComputedFrom";

describe("madeIn", () => {
  it("says what was asked in one line", () => {
    const line = madeIn({ kind: "within", metric: "along layer 'ROADS' of map data 7", from: "yard", to: "hotspot",
      computed_at: "2026-10-01T12:50:00+00:00", request: { max_min: 15 } });
    expect(line).toContain("0/1 within 15 min");
    expect(line).toContain("yard → hotspot");
    expect(line).toContain("ROADS");
  });
});
