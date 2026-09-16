import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getToken, setToken } from "./client";

describe("apiFetch", () => {
  beforeEach(() => {
    setToken(null);
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the Authorization header when a token is stored", async () => {
    setToken("test-token");
    (fetch as any).mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await apiFetch("/api/iam/organization/");

    const [, options] = (fetch as any).mock.calls[0];
    expect(options.headers.get("Authorization")).toBe("Bearer test-token");
  });

  it("clears the token and throws on a 401 response", async () => {
    setToken("stale-token");
    (fetch as any).mockResolvedValue(new Response("unauthorized", { status: 401 }));

    await expect(apiFetch("/api/iam/organization/")).rejects.toThrow();
    expect(getToken()).toBeNull();
  });
});
