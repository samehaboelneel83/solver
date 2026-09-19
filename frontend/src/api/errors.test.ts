import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { formatApiError } from "./errors";

describe("formatApiError", () => {
  it("formats a 422 validation error as one line per field", () => {
    const err = new ApiError(
      422,
      JSON.stringify({ detail: [{ loc: ["body", "code"], msg: "Field required" }] })
    );
    expect(formatApiError(err)).toBe("code: Field required");
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
    expect(formatApiError(err)).toBe("code: Field required\nname: String too short");
  });

  it("joins every loc segment after the leading body/query/path marker with a dot", () => {
    const err = new ApiError(
      422,
      JSON.stringify({ detail: [{ loc: ["body", "attributes", "rank"], msg: "Invalid value" }] })
    );
    expect(formatApiError(err)).toBe("attributes.rank: Invalid value");
  });

  describe("422 with an object detail (a database validation trigger)", () => {
    // Schema v1's `entity_validate` trigger raises a structured error that
    // the backend turns into a 422 whose `detail` is an object rather than
    // FastAPI's list. These are real response bodies, copied from
    // backend/tests/test_api_entities.py.

    it('renders a trigger 422 as "<field>: <message>", like the list branch', () => {
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: {
            message: 'entity ahmed: attribute "rank" must be integer',
            field: "rank",
            kind: "attribute_type",
          },
        })
      );
      expect(formatApiError(err)).toBe('rank: entity ahmed: attribute "rank" must be integer');
    });

    it("does not show the user raw JSON", () => {
      // The defect this branch fixes: before it, the object fell through to
      // JSON.stringify and `kind`/`field` were shown as machine vocabulary.
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: {
            message: 'entity ahmed: unknown attribute "nope"',
            field: "nope",
            kind: "unknown_attribute",
          },
        })
      );
      const text = formatApiError(err);
      expect(text).not.toContain("{");
      expect(text).not.toContain("kind");
    });

    it("falls back to the message alone when the failure names no field", () => {
      // `translate_db_error` reads `field` off the trigger's payload, and
      // the `parameter_index` kind carries `entity_ids` instead -- so
      // `field` arrives null and must not be printed as a prefix.
      const err = new ApiError(
        422,
        JSON.stringify({
          detail: { message: "parameter_value: index does not match", field: null, kind: "x" },
        })
      );
      expect(formatApiError(err)).toBe("parameter_value: index does not match");
    });

    it("still JSON-stringifies a 422 object that is not the trigger shape", () => {
      // No `message`, so there is nothing better to show than the body.
      const err = new ApiError(422, JSON.stringify({ detail: { code: "weird" } }));
      expect(formatApiError(err)).toBe(JSON.stringify({ code: "weird" }));
    });
  });

  it("renders a non-string, non-array detail as JSON", () => {
    const err = new ApiError(400, JSON.stringify({ detail: { code: "conflict", reason: "locked" } }));
    expect(formatApiError(err)).toBe(JSON.stringify({ code: "conflict", reason: "locked" }));
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
