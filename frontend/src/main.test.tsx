import { describe, expect, it } from "vitest";
import { shouldRetry } from "./main";
import { ApiError } from "./api/client";

describe("shouldRetry", () => {
  it("never retries a 404 (client error)", () => {
    expect(shouldRetry(0, new ApiError(404, "not found"))).toBe(false);
  });

  it("retries a 500 once, then stops", () => {
    const error = new ApiError(500, "server error");
    expect(shouldRetry(0, error)).toBe(true);
    expect(shouldRetry(1, error)).toBe(false);
  });

  it("retries a plain (network) error once, then stops", () => {
    const error = new Error("network failure");
    expect(shouldRetry(0, error)).toBe(true);
    expect(shouldRetry(1, error)).toBe(false);
  });
});
