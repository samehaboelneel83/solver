import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { serverExpressionProblems } from "./serverProblems";

function refusal(...items: { loc: (string | number)[]; msg: string; kind?: string }[]) {
  return new ApiError(
    422,
    JSON.stringify({ detail: items.map((item) => ({ type: "value_error", ...item })) })
  );
}

describe("serverExpressionProblems", () => {
  it("reads the rule path out of loc", () => {
    expect(
      serverExpressionProblems(
        refusal({ loc: ["query", "expr", "query", "rules", 1, "rules", 0, "value"], msg: "nope" })
      )
    ).toEqual([{ path: [1, 0], message: "nope" }]);
  });

  it("maps the document as a whole to the root path", () => {
    expect(
      serverExpressionProblems(refusal({ loc: ["query", "expr", "version"], msg: "old" }))
    ).toEqual([{ path: [], message: "old" }]);
  });

  it("ignores entries that are not about the expression", () => {
    expect(
      serverExpressionProblems(
        refusal(
          { loc: ["query", "limit"], msg: "too big" },
          { loc: ["body", "attrs"], msg: "not an object" },
          { loc: ["query", "expr", "query", "rules", 2, "operator"], msg: "mine" }
        )
      )
    ).toEqual([{ path: [2], message: "mine" }]);
  });

  it("keys on loc rather than on kind (Ruling 30)", () => {
    // The same `loc` with and without a `kind` must map identically: `kind`
    // says WHO judged, `loc` says WHAT was wrong, and the expression
    // compiler is not a database trigger so it sends none.
    const withKind = serverExpressionProblems(
      refusal({ loc: ["query", "expr", "query", "rules", 0, "value"], msg: "x", kind: "attribute_type" })
    );
    const without = serverExpressionProblems(
      refusal({ loc: ["query", "expr", "query", "rules", 0, "value"], msg: "x" })
    );
    expect(withKind).toEqual(without);
    expect(withKind).toEqual([{ path: [0], message: "x" }]);
  });

  it("is empty for anything that is not a 422 about an expression", () => {
    expect(serverExpressionProblems(new ApiError(500, "boom"))).toEqual([]);
    expect(serverExpressionProblems(new ApiError(422, "not json"))).toEqual([]);
    expect(serverExpressionProblems(new ApiError(409, JSON.stringify({ detail: "clash" })))).toEqual([]);
    expect(serverExpressionProblems(new Error("plain"))).toEqual([]);
    expect(serverExpressionProblems(null)).toEqual([]);
  });

  it("does not mistake a body-shaped loc for a query-shaped one", () => {
    expect(
      serverExpressionProblems(refusal({ loc: ["body", "expr", "query", "rules", 0], msg: "x" }))
    ).toEqual([]);
  });
});
