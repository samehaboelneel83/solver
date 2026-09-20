import { describe, expect, it } from "vitest";
import { graphQueryPath, graphQueryKey, relationshipErrorMessage } from "./graph";
import { ApiError } from "./client";

describe("graphQueryPath", () => {
  it("asks the v1 graph route for a domain, with the hierarchy relationship type when one is chosen", () => {
    expect(graphQueryPath(7, 3)).toBe("/api/v1/graph?domain_id=7&hierarchy_type_id=3");
  });

  it("omits hierarchy_type_id when no hierarchy is chosen", () => {
    expect(graphQueryPath(7, null)).toBe("/api/v1/graph?domain_id=7");
  });
});

describe("graphQueryKey", () => {
  it("lives under the v1 namespace, so a v1 write invalidates the drawn graph too", () => {
    expect(graphQueryKey(7, 3)[0]).toBe("v1");
    expect(graphQueryKey(7, 3)).toEqual(["v1", "graph", 7, 3]);
  });
});

function error422(detail: unknown): ApiError {
  return new ApiError(422, JSON.stringify({ detail }));
}

describe("relationshipErrorMessage", () => {
  it("shows a trigger message on its own when loc names the relationship type rather than a body field", () => {
    // The trigger sets `field` to the relationship type's NAME (Task 7), so
    // `loc[1]` is "reports_to" here, not a column. Prefixing it the way
    // formatApiError does would read 'reports_to: relationship "reports_to":
    // would create a cycle'.
    const message = relationshipErrorMessage(
      error422([
        {
          loc: ["body", "reports_to"],
          msg: 'relationship "reports_to": would create a cycle',
          kind: "cycle",
        },
      ])
    );
    expect(message).toBe('relationship "reports_to": would create a cycle');
  });

  it("keeps the same shape for a cardinality violation, which is a different kind at the same loc", () => {
    // Ruling 30: the branch is on `loc`, not on `kind` -- so a kind this code
    // has never heard of still renders as a message rather than as raw JSON.
    const message = relationshipErrorMessage(
      error422([
        {
          loc: ["body", "manages"],
          msg: 'relationship "manages": target already has a source',
          kind: "cardinality",
        },
      ])
    );
    expect(message).toBe('relationship "manages": target already has a source');
  });

  it("names the field when loc points at a real body field of the relationship write", () => {
    const message = relationshipErrorMessage(
      error422([{ loc: ["body", "to_entity_id"], msg: "Input should be a valid integer" }])
    );
    expect(message).toBe("to_entity_id: Input should be a valid integer");
  });

  it("joins several entries, one per line", () => {
    const message = relationshipErrorMessage(
      error422([
        { loc: ["body", "to_entity_id"], msg: "Input should be a valid integer" },
        { loc: ["body", "owns"], msg: 'relationship "owns": entity types do not match', kind: "type_mismatch" },
      ])
    );
    expect(message).toBe(
      'to_entity_id: Input should be a valid integer\nrelationship "owns": entity types do not match'
    );
  });

  it("decides by loc even where kind would say otherwise (Ruling 30)", () => {
    // Keying on `kind` gives the same answer for today's two shapes (trigger
    // entries carry kind AND a type-name loc; Pydantic's carry neither), so
    // only these two cross cases can tell the rules apart: a kind-less entry
    // about the relationship as a whole, and a kind-carrying one about a
    // body field. `loc` says WHAT was wrong; `kind` only says who judged it.
    const message = relationshipErrorMessage(
      error422([
        { loc: ["body", "reports_to"], msg: 'relationship "reports_to": source already has a target' },
        { loc: ["body", "to_entity_id"], msg: "entity 42 does not exist", kind: "type_mismatch" },
      ])
    );
    expect(message).toBe(
      'relationship "reports_to": source already has a target\nto_entity_id: entity 42 does not exist'
    );
  });

  it("falls back to the shared formatter for anything that is not a list-shaped 422", () => {
    expect(relationshipErrorMessage(new ApiError(409, JSON.stringify({ detail: "relationship already exists" })))).toBe(
      "relationship already exists"
    );
  });
});
