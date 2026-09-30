import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Health from "./Health";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch, NetworkError } from "../api/client";

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><Health /></MemoryRouter>
  </QueryClientProvider>);
}

describe("the Health page", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("names each part, and for one that is down the command that brings it back", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ready: false, checks: [
      { name: "Database", ok: true, needed: true, says: "PostgreSQL answers.", fix: null },
      { name: "Worker", ok: false, needed: true, says: "No worker has been seen.", fix: "Start it with: docker compose up -d worker" },
      { name: "Analytics store", ok: false, needed: false, says: "ClickHouse does not answer.", fix: "docker compose up -d clickhouse" },
    ] });
    mount();
    expect(await screen.findByText("1 part is down: planning needs it.")).toBeInTheDocument();
    expect(screen.getByText("Start it with: docker compose up -d worker")).toBeInTheDocument();
    expect(screen.getByText("Down")).toBeInTheDocument();
    expect(screen.getByText("Not working")).toBeInTheDocument();
    expect(screen.getByText("Working")).toBeInTheDocument();
  });

  it("says when everything works", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({ ready: true, checks: [{ name: "Database", ok: true, needed: true, says: "PostgreSQL answers.", fix: null }] });
    mount();
    expect(await screen.findByText("Everything is working.")).toBeInTheDocument();
  });

  it("tells how to start the server when it does not answer at all", async () => {
    vi.mocked(apiFetch).mockImplementation(async () => { throw new NetworkError(); });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server does not answer.");
  });
});
