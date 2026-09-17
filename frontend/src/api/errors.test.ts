import { describe, expect, it } from "vitest";
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
});
