import { describe, expect, it } from "vitest";
import { timeScore } from "./TimesTooClose";
import type { EntityType } from "../api/v1";

const kind = (name: string, attrs: [string, string][]) =>
  ({ id: 1, name, attributes: attrs.map(([n, t]) => ({ name: n, data_type: t })) }) as unknown as EntityType;

describe("timeScore", () => {
  it("ranks a block of hours above a list of names", () => {
    const block = kind("time_block", [["block_id", "text"], ["day", "integer"], ["start_hour", "integer"], ["hours", "integer"]]);
    const district = kind("district", [["district_id", "text"], ["name", "text"]]);
    expect(timeScore(block)).toBeGreaterThan(timeScore(district));
  });
});

describe("timeScore with imported choices", () => {
  it("puts a day/start/end block above a person with shift limits", () => {
    const block = kind("time_block", [["day", "date"], ["start", "enum"], ["end", "enum"]]);
    const operator = kind("operator", [["name", "text"], ["max_shifts", "integer"], ["min_rest_hours", "integer"]]);
    expect(timeScore(block)).toBeGreaterThan(timeScore(operator));
  });
});
