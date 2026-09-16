import { describe, expect, it } from "vitest";
import { graphQueryPath } from "./graph";

describe("graphQueryPath", () => {
  it("includes hierarchy_id when given", () => {
    expect(graphQueryPath("org-1", "hier-1")).toBe("/api/graph/domain?organization_id=org-1&hierarchy_id=hier-1");
  });

  it("omits hierarchy_id when null", () => {
    expect(graphQueryPath("org-1", null)).toBe("/api/graph/domain?organization_id=org-1");
  });
});
