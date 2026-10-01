import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import People from "./People";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { ApiError, apiFetch } from "../api/client";

const roles = [
  { id: "r1", code: "planner", name: "Planner", capabilities: ["run.submit"], users: 0 },
  { id: "r2", code: "admin", name: "Administrator", capabilities: ["iam.manage", "model.publish"], users: 1 },
];
let users: { id: string; username: string; display_name: string | null; email: null; is_active: boolean; roles: { id: string; code: string; name: string }[] }[];

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><People /></MemoryRouter>
  </QueryClientProvider>);
}

describe("People & roles", () => {
  beforeEach(() => {
    users = [
      { id: "u1", username: "admin", display_name: "Administrator", email: null, is_active: true, roles: [{ id: "r2", code: "admin", name: "Administrator" }] },
      { id: "u2", username: "planner-a", display_name: "Planner", email: null, is_active: true, roles: [] },
      { id: "u3", username: "planner-b", display_name: "Planner", email: null, is_active: true, roles: [] },
    ];
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === "/api/v1/people") return { users, roles };
      if (path === "/api/v1/people/u2/roles") {
        const ids = JSON.parse(String(options?.body)).role_ids as string[];
        users = users.map((u) => (u.id === "u2" ? { ...u, roles: roles.filter((r) => ids.includes(r.id)) } : u));
        return users[1];
      }
      if (path === "/api/v1/people/u1") throw new ApiError(422, JSON.stringify({ detail: "You cannot deactivate your own account." }));
      throw new Error(`Unexpected ${path}`);
    });
  });

  it("says who holds no role, telling apart two people with the same name (UX audit A-1)", async () => {
    mount();
    expect(await screen.findByRole("note")).toHaveTextContent(
      "2 people have no role, so they can sign in but do nothing: Planner (planner-a), Planner (planner-b).");
    expect(screen.getAllByText("No role: can sign in, but do nothing")).toHaveLength(2);
    const planner = screen.getByRole("rowheader", { name: /planner-a/ }).closest("tr")!;
    expect(within(planner).queryByText("token_version")).toBeNull();
  });

  it("gives a person a role in place", async () => {
    mount();
    const row = (await screen.findByRole("rowheader", { name: /planner-a/ })).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Change roles" }));
    fireEvent.click(within(row).getByLabelText("Planner"));
    fireEvent.click(within(row).getByRole("button", { name: "Save roles" }));
    await waitFor(() => expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/api/v1/people/u2/roles",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ role_ids: ["r1"] }) })));
    await waitFor(() => expect(screen.getByRole("note")).toHaveTextContent("1 person has no role"));
  });

  it("lists each role with what it allows and how many hold it (A-2), and says why a change is refused", async () => {
    mount();
    const roleRow = (await screen.findByRole("rowheader", { name: /^Planner planner$/ })).closest("tr")!;
    expect(roleRow).toHaveTextContent("1 permission: run.submit");
    const people = screen.getByRole("region", { name: "People" });
    const me = within(people).getByRole("rowheader", { name: /^Administrator admin$/ });
    fireEvent.click(within(me.closest("tr")!).getByRole("button", { name: "Deactivate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You cannot deactivate your own account.");
  });
});
