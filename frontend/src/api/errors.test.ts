import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { formatApiError } from "./errors";

describe("formatApiError", () => {
  it("formats a 422 validation error as one line per field", () => {
    const err = new ApiError(
      422,
      JSON.stringify({ detail: [{ loc: ["body", "code"], msg: "Field required" }] })
    );
    expect(formatApiError(err)).toBe("code is required");
  });

  it("formats a 422 with multiple field errors as multiple lines", () => {
    const err = new ApiError(
      422,
      JSON.stringify({
        detail: [
          { loc: ["body", "code"], msg: "Field required" },
          { loc: ["body", "name"], msg: "String too short" },
        ],
      })
    );
    expect(formatApiError(err)).toBe("code is required\nname: String too short");
  });

  it("joins every loc segment after the leading body/query/path marker with a dot", () => {
    const err = new ApiError(
      422,
      JSON.stringify({ detail: [{ loc: ["body", "attributes", "rank"], msg: "Invalid value" }] })
    );
    expect(formatApiError(err)).toBe("attributes.rank: Invalid value");
  });

  describe("422 from a database validation trigger (Ruling 19's single shape)", () => {
    // Schema v1's validation triggers (`entity_validate`,
    // `relationship_validate`, `parameter_value_validate`) are turned by the
    // backend's `translate_db_error` into a 422 in FastAPI's own list shape,
    // with the trigger's `kind` as a sibling key on the entry. Task 3 had
    // emitted an *object* detail instead; Ruling 19 normalised it, so the
    // list branch now renders every 422. These bodies are copied verbatim
    // from real backend responses (task 7, captured over HTTP).

    it('renders an entity trigger 422 as "<field>: <msg>"', () => {
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: [
            {
              type: "value_error",
              loc: ["body", "nope"],
              msg: 'entity ahmed: unknown attribute "nope"',
              kind: "unknown_attribute",
            },
          ],
        })
      );
      expect(formatApiError(err)).toBe('nope: entity ahmed: unknown attribute "nope"');
    });

    it("renders a relationship trigger 422, whose field is the relationship type's name", () => {
      // `relationship_validate` blames the relationship *type* by name, not
      // a column -- so the prefix is "reports_to", which is what a user
      // needs in order to know which kind of link they broke.
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: [
            {
              type: "value_error",
              loc: ["body", "reports_to"],
              msg: 'relationship "reports_to": would create a cycle',
              kind: "cycle",
            },
          ],
        })
      );
      expect(formatApiError(err)).toBe('reports_to: relationship "reports_to": would create a cycle');
    });

    it("never shows the user the machine-readable kind or raw JSON", () => {
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: [
            {
              type: "value_error",
              loc: ["body", "entity_ids"],
              msg: "parameter_value: index does not match",
              kind: "parameter_index",
            },
          ],
        })
      );
      const text = formatApiError(err);
      expect(text).toBe("entity_ids: parameter_value: index does not match");
      expect(text).not.toContain("{");
      expect(text).not.toContain("parameter_index");
    });

    it("renders the message alone when loc names no field beyond the request part", () => {
      // `translate_db_error` blames `["body"]` when a trigger payload names
      // no field (none does today, but the branch exists), and FastAPI does
      // the same for a model-level validator. "body: ..." is request-part
      // plumbing, not a field name, and must not be shown as one.
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: [{ type: "value_error", loc: ["body"], msg: "the row as a whole is invalid", kind: "x" }],
        })
      );
      expect(formatApiError(err)).toBe("the row as a whole is invalid");
    });

    it("no longer special-cases the retired object shape", () => {
      // Pins that task 6's object branch is gone, not merely unused: an
      // object `detail` now takes the generic non-array path like any other
      // unrecognised body. No backend route emits this shape any more.
      const err = new ApiError(
        422,
        JSON.stringify({ detail: { message: "m", field: "f", kind: "k" } })
      );
      // Its own sentence is what a person reads (benchmark, October 2026: raw JSON was shown).
      expect(formatApiError(err)).toBe("m");
    });
  });

  it("renders a non-string, non-array detail as JSON", () => {
    const err = new ApiError(400, JSON.stringify({ detail: { code: "conflict", reason: "locked" } }));
    expect(formatApiError(err)).toBe("code: conflict; reason: locked");
  });

  it("formats a 409 conflict with a plain-text detail", () => {
    const err = new ApiError(409, JSON.stringify({ detail: "x already exists" }));
    expect(formatApiError(err)).toBe("x already exists");
  });

  it("formats a 404 with a plain-text detail", () => {
    const err = new ApiError(404, JSON.stringify({ detail: "not found" }));
    expect(formatApiError(err)).toBe("not found");
  });

  it("formats a 5xx as a generic server error", () => {
    const err = new ApiError(500, "Internal Server Error");
    expect(formatApiError(err)).toBe("Server error (500). Please try again.");
  });

  it("falls back to the raw message for a plain Error", () => {
    const err = new Error("boom");
    expect(formatApiError(err)).toBe("boom");
  });

  describe("offline branching (D-7)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("shows a plain-English offline message for a network-level Error when navigator.onLine is false", () => {
      vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
      // The real browser message for a dropped connection is something like "Failed to fetch" --
      // opaque to an end user, and distinct per browser.
      const err = new Error("Failed to fetch");

      expect(formatApiError(err)).toBe("You appear to be offline. Check your connection and try again.");
    });

    it("still shows the raw message when navigator.onLine is true (D-2's status-code branching is untouched)", () => {
      vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(true);
      const err = new Error("Failed to fetch");

      expect(formatApiError(err)).toBe("Failed to fetch");
    });

    it("does not apply the offline branch to an ApiError -- 5xx/4xx formatting is unchanged offline", () => {
      vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
      const err = new ApiError(500, "Internal Server Error");

      expect(formatApiError(err)).toBe("Server error (500). Please try again.");
    });
  });
});

describe("validation in plain words (benchmark, October 2026)", () => {
  it("says what a limit means instead of the validator's text", async () => {
    const { plainValidation } = await import("./errors");
    expect(plainValidation("Input should be less than or equal to 20000")).toBe("must be at most 20000");
    expect(plainValidation("Field required")).toBe("is required");
    expect(plainValidation("String should match pattern '^[a-z][a-z0-9_]*$'")).toBe("must be lower-case letters, digits and _, starting with a letter");
    expect(plainValidation("something else")).toBe("something else");
  });
});
