import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ReachabilityBanner from "./ReachabilityBanner";
import { NetworkError } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

describe("ReachabilityBanner", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("is silent when health is ok", async () => {
    (apiFetch as any).mockResolvedValue({ postgres: "ok", clickhouse: "ok" });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReachabilityBanner />
      </QueryClientProvider>
    );
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(screen.queryByTestId("offline-notice")).not.toBeInTheDocument();
    expect(screen.queryByTestId("degraded-notice")).not.toBeInTheDocument();
  });

  it("warns when the API cannot be reached", async () => {
    (apiFetch as any).mockRejectedValue(new NetworkError());
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReachabilityBanner />
      </QueryClientProvider>
    );
    expect(await screen.findByTestId("offline-notice")).toHaveAttribute("data-reason", "unreachable");
    expect(screen.getByTestId("offline-notice")).toHaveTextContent(/platform API/i);
  });

  it("warns when postgres is unhealthy", async () => {
    (apiFetch as any).mockResolvedValue({ postgres: "error", clickhouse: "ok" });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReachabilityBanner />
      </QueryClientProvider>
    );
    expect(await screen.findByTestId("degraded-notice")).toHaveTextContent(/database/i);
  });

  function renderAs(capabilities: string[]) {
    (apiFetch as any).mockImplementation((path: string) =>
      Promise.resolve(path.startsWith("/api/v1/me") ? { username: "u", capabilities } : { postgres: "ok", clickhouse: "error" })
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReachabilityBanner />
      </QueryClientProvider>
    );
  }

  it("keeps an analytics-only fault from people who cannot fix it", async () => {
    localStorage.clear();
    renderAs(["domain.edit"]);
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("degraded-notice")).not.toBeInTheDocument();
  });

  it("tells an administrator, who may hide it for the session", async () => {
    localStorage.clear();
    renderAs(["settings.edit"]);
    expect(await screen.findByTestId("degraded-notice")).toHaveTextContent("The analytics store reported an error");
    fireEvent.click(screen.getByRole("button", { name: "Hide until it is back" }));
    expect(screen.queryByTestId("degraded-notice")).not.toBeInTheDocument();
    expect(localStorage.getItem("solver_analytics_notice_hidden")).toBe("1");
  });
});
