import { describe, expect, it } from "vitest";
import { fillIndices } from "./terms";

describe("filling a read's cells", () => {
  it("gives two cells of one set the two names bound for it, and one name to both when there is one", () => {
    const two = [{ index: "v", set: "vehicle" }, { index: "c", set: "customer" }, { index: "c2", set: "customer" }];
    expect(fillIndices(2, ["customer", "customer"], two)).toEqual(["c", "c2"]);
    expect(fillIndices(2, ["customer", "customer"], [{ index: "c", set: "customer" }])).toEqual(["c", "c"]);
    expect(fillIndices(2, ["vehicle", "depot"], two)).toEqual(["v", ""]);
  });
});
