import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OpsQueue from "./OpsQueue";
import OpsAudit from "./OpsAudit";
import OpsBackups from "./OpsBackups";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn(), apiText: vi.fn(), apiDownload: vi.fn() };
});

const clientMod = await import("../api/client");
const mockFetch = clientMod.apiFetch as unknown as ReturnType<typeof vi.fn>;
const mockText = clientMod.apiText as unknown as ReturnType<typeof vi.fn>;

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockText.mockReset();
});

describe("OpsQueue", () => {
  it("shows per-org depth and wait", async () => {
    mockText.mockResolvedValue('queue_depth{org="demo"} 2\nruns_running{org="demo"} 1\nqueue_oldest_wait_seconds{org="demo"} 30\n');
    wrap(<OpsQueue />);
    expect(await screen.findByRole("heading", { name: "Run queue" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("30 s")).toBeInTheDocument();
  });
});

describe("OpsAudit", () => {
  it("lists audit events", async () => {
    mockFetch.mockResolvedValue({
      total: 1,
      items: [
        {
          id: 1,
          at: "2026-09-26T12:00:00Z",
          organization_id: "org",
          actor_id: "actor-1234",
          api_key_id: null,
          action: "login",
          object_type: "session",
          object_id: null,
          before_hash: null,
          after_hash: null,
          ip: "127.0.0.1",
        },
      ],
    });
    wrap(<OpsAudit />);
    expect(await screen.findByRole("heading", { name: "Audit history" })).toBeInTheDocument();
    expect(await screen.findByText("login")).toBeInTheDocument();
    expect(screen.getByText("1 events")).toBeInTheDocument();
  });
});

describe("OpsBackups", () => {
  it("shows RPO and last dump", async () => {
    mockFetch.mockResolvedValue({
      root: "/backups",
      reachable: true,
      rpo_hours: 24,
      rto_hours: 4,
      latest: { night: "2026-09-26", dump: "solver-2026-09-26.dump", bytes: "100" },
      dumps: ["solver-2026-09-26.dump"],
      dump_count: 1,
      wal_present: true,
      runbook: "docs/runbooks/backups.md",
    });
    wrap(<OpsBackups />);
    expect(await screen.findByRole("heading", { name: "Backups & recovery" })).toBeInTheDocument();
    expect(await screen.findByText(/RPO 24 h/)).toBeInTheDocument();
    expect(screen.getAllByText(/solver-2026-09-26\.dump/).length).toBeGreaterThan(0);
  });
});
