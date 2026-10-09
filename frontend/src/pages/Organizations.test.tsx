import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ known: true, can: () => true }) }));
import { ApiError, apiFetch } from "../api/client";
import Organizations from "./Organizations";

const QUOTA = { tier: "standard", limits: { max_concurrent_runs: 4, max_vars: null }, this_month: { cpu_seconds: 120.4, runs: 12 } };
const ORGS = { items: [
  { id: "o1", code: "default", name: "Default", is_active: true, is_operator: true, created_at: "", users: 3, problems: 9, quota: { tier: "enterprise" } },
  { id: "o2", code: "acme", name: "Acme", is_active: true, is_operator: false, created_at: "", users: 1, problems: 0, quota: { tier: "free", max_vars: 1000 } },
] };

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><Organizations /></MemoryRouter></QueryClientProvider>);
}
const sent = (path: string) => vi.mocked(apiFetch).mock.calls.filter(([p]) => p === path)
  .map(([, i]) => ({ method: (i as RequestInit | undefined)?.method, body: (i as RequestInit | undefined)?.body ? JSON.parse(String((i as RequestInit).body)) : undefined }));

describe("organizations and sign-in, in the platform itself", () => {
  let operator: boolean;
  beforeEach(() => {
    operator = true;
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      const p = String(path);
      if (p === "/api/v1/quota") return QUOTA;
      if (p === "/api/v1/sso/provider") return { configured: false };
      if (p === "/api/v1/scim/token") return { token: "scim-abc", token_type: "Bearer" };
      if (p === "/api/v1/organizations") {
        if (!operator) throw new ApiError(403, "only the operator");
        return ORGS;
      }
      if (p.startsWith("/api/v1/organizations/")) return {};
      throw new Error(`unexpected ${p}`);
    });
  });

  it("starts an organization with its first administrator, sets a quota and deletes one by its code", async () => {
    mount();
    const table = await screen.findByRole("table", { name: "Organizations" });
    expect(table).toHaveTextContent("default (operator)");
    const form = screen.getByRole("form", { name: "Start an organization" });
    fireEvent.change(within(form).getByLabelText("Code (lower-case, unique)"), { target: { value: "globex" } });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Globex" } });
    fireEvent.change(within(form).getByLabelText("First administrator's user name"), { target: { value: "globex.admin" } });
    fireEvent.change(within(form).getByLabelText(/Their first password/), { target: { value: "a long first secret" } });
    fireEvent.click(within(form).getByRole("button", { name: "Start it" }));
    await waitFor(() => expect(sent("/api/v1/organizations").some((c) => c.method === "POST")).toBe(true));
    expect(sent("/api/v1/organizations").find((c) => c.method === "POST")!.body).toEqual({
      code: "globex", name: "Globex", admin_username: "globex.admin", admin_password: "a long first secret", tier: "standard" });

    const acme = within(table).getByText("acme").closest("tr")!;
    fireEvent.click(within(acme).getByRole("button", { name: "Quota" }));
    fireEvent.change(screen.getByLabelText("acme: Decisions per model"), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save the quota" }));
    await waitFor(() => expect(sent("/api/v1/organizations/o2/quota")[0]).toEqual({ method: "PUT", body: { tier: "free", max_vars: 5000 } }));

    fireEvent.click(within(acme).getByRole("button", { name: "Delete" }));
    const gone = screen.getByRole("button", { name: "Delete acme" });
    expect(gone).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type acme to confirm"), { target: { value: "acme" } });
    fireEvent.click(gone);
    await waitFor(() => expect(sent("/api/v1/organizations/o2/delete")[0]).toEqual({ method: "POST", body: { confirm_code: "acme" } }));
  });

  it("shows its own limits and sets up sign-on and directory sync; no list for a tenant", async () => {
    operator = false;
    mount();
    expect(await screen.findByText(/Tier standard; this month 12 runs, 120 CPU seconds/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Issuer (https://…)"), { target: { value: "https://login.acme.example" } });
    fireEvent.change(screen.getByLabelText("Client id"), { target: { value: "solver" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "s3cret" } });
    fireEvent.change(screen.getByLabelText(/Groups to roles/), { target: { value: "planners=planner, it=admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Save sign-on" }));
    await waitFor(() => expect(sent("/api/v1/sso/provider").find((c) => c.method === "PUT")?.body).toEqual({
      issuer: "https://login.acme.example", client_id: "solver", client_secret: "s3cret", scopes: "openid profile email",
      group_claim: "groups", sso_required: false, role_map: { planners: "planner", it: "admin" } }));
    fireEvent.click(screen.getByRole("button", { name: "Make a new token" }));
    expect(await screen.findByText("scim-abc")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Organizations" })).not.toBeInTheDocument();
  });
});
