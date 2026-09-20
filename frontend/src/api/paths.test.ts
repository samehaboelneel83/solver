import { describe, expect, it } from "vitest";
import { tableApiPath } from "./paths";

describe("tableApiPath", () => {
  it("collapses the public schema, matching the backend's route prefix", () => {
    expect(tableApiPath("public", "domain")).toBe("/api/domain");
    expect(tableApiPath("public", "problem")).toBe("/api/problem");
  });

  it("keeps the schema segment for every other schema", () => {
    expect(tableApiPath("iam", "role")).toBe("/api/iam/role");
  });

  it("does not collapse a table merely named public", () => {
    expect(tableApiPath("iam", "public")).toBe("/api/iam/public");
  });
});
