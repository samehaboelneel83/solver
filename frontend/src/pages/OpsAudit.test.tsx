import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import OpsAudit from "./OpsAudit";

const row = { at: "2026-09-29T08:00:00Z", organization_id: "o", before_hash: null, after_hash: null, ip: null, object_type: "problem", object_id: "3" };

describe("audit history (operator trial F30)", () => {
  it("names who acted: the username, the API key's name, or the platform itself", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ total: 3, items: [
      { ...row, id: 1, action: "template.apply", actor_id: "a4be658d-0000", actor: "admin", api_key_id: null, api_key_name: null },
      { ...row, id: 2, action: "run.create", actor_id: null, actor: null, api_key_id: "k1", api_key_name: "nightly" },
      { ...row, id: 3, action: "integration.extract", actor_id: null, actor: null, api_key_id: null, api_key_name: null },
    ] });
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><OpsAudit /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.getByText("API key nightly")).toBeInTheDocument();
    expect(screen.getByText("the platform")).toBeInTheDocument();
    expect(screen.queryByText("a4be658d")).not.toBeInTheDocument();
  });
});
