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

  it("redirects to /login with reason=expired and the current path on a 401", async () => {
    vi.stubGlobal("location", { pathname: "/finance/invoice/42", search: "?tab=details", href: "" });
    setToken("stale-token");
    (fetch as any).mockResolvedValue(new Response("unauthorized", { status: 401 }));

    await expect(apiFetch("/api/iam/organization/")).rejects.toThrow();

    expect(window.location.href).toBe(
      "/login?reason=expired&next=" + encodeURIComponent("/finance/invoice/42?tab=details")
    );
  });

  it("does not redirect again when already on the login page", async () => {
    vi.stubGlobal("location", { pathname: "/login", search: "", href: "" });
    setToken("stale-token");
    (fetch as any).mockResolvedValue(new Response("unauthorized", { status: 401 }));

    await expect(apiFetch("/api/iam/organization/")).rejects.toThrow();

    expect(window.location.href).toBe("");
  });

  it("throws NetworkError when fetch itself fails", async () => {
    (fetch as any).mockRejectedValue(new TypeError("Failed to fetch"));
    const { NetworkError } = await import("./client");
    await expect(apiFetch("/api/health")).rejects.toBeInstanceOf(NetworkError);
  });
});
