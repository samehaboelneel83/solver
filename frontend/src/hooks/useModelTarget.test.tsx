import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useModelTarget } from "./useModelTarget";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string) => {
    if (path.includes("/api/problem/")) {
      return { items: [{ id: 1, name: "Alpha" }, { id: 2, name: "Beta" }] };
    }
    return { items: [] };
  }),
}));

vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useVersions: () => ({
      data: { items: [{ id: 10, version: 2, problem_id: 1, ir_hash: "a", created_at: "", note: null }] },
      isLoading: false,
    }),
  };
});

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useModelTarget", () => {
  it("defaults to the first problem when nothing was requested", async () => {
    const { result } = renderHook(() => useModelTarget(1, { problemId: null, versionId: null }, true), {
      wrapper: ({ children }) => wrap(children),
    });
    await waitFor(() => expect(result.current.problemId).toBe(1));
    expect(result.current.problemMissing).toBe(false);
  });

  it("does not substitute another problem when an explicit id is missing", async () => {
    const { result } = renderHook(() => useModelTarget(1, { problemId: 99, versionId: null }, true), {
      wrapper: ({ children }) => wrap(children),
    });
    await waitFor(() => expect(result.current.problemMissing).toBe(true));
    expect(result.current.problemId).toBeNull();
  });
});
