import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const access = vi.hoisted(() => ({ capabilities: ["domain.edit"] }));
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ known: true, can: (c: string) => access.capabilities.includes(c) }) }));
vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import DomainChooser from "./DomainChooser";

function Landed() {
  return <p data-testid="landed">{useLocation().pathname}</p>;
}

function mount(path = "/domains") {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="/domains" element={<DomainChooser />} />
      <Route path="/domains/:id/*" element={<Landed />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

describe("choosing a domain (Epic UX, U-1)", () => {
  beforeEach(() => {
    access.capabilities = ["domain.edit"];
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path, init) => {
      if ((init as RequestInit | undefined)?.method === "POST") return { id: 9, name: JSON.parse(String((init as RequestInit).body)).name };
      const q = new URLSearchParams(String(path).split("?")[1]).get("q");
      const all = [{ id: 1, name: "Hospital rota" }, { id: 2, name: "Fleet" }];
      const items = q ? all.filter((d) => d.name.toLowerCase().includes(q.toLowerCase())) : all;
      return { items, total: items.length };
    });
  });

  it("lists domains linking to their overview", async () => {
    mount();
    expect(await screen.findByRole("link", { name: /Hospital rota/ })).toHaveAttribute("href", "/domains/1/overview");
  });

  it("goes on to the page an old hub link asked for, and only to a page the app has", async () => {
    mount("/domains?next=data/parameters");
    expect(await screen.findByRole("link", { name: /Fleet/ })).toHaveAttribute("href", "/domains/2/data/parameters");
  });

  it("ignores a next that is not one of its pages", async () => {
    mount("/domains?next=https://evil.example");
    expect(await screen.findByRole("link", { name: /Fleet/ })).toHaveAttribute("href", "/domains/2/overview");
  });

  it("searches on the server and says when nothing matches", async () => {
    mount();
    await screen.findByRole("link", { name: /Fleet/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search workspaces" }), { target: { value: "zzz" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No workspaces match"));
    expect(vi.mocked(apiFetch).mock.calls.some(([p]) => String(p).includes("q=zzz"))).toBe(true);
  });

  it("creates a domain from the empty install and opens it", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, init) => {
      if ((init as RequestInit | undefined)?.method === "POST") return { id: 9, name: "Hospital staffing" };
      return { items: [], total: 0 };
    });
    mount();
    expect(await screen.findByText("There are no domains yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "start from a template on Home" })).toHaveAttribute("href", "/#templates");
    fireEvent.click(screen.getByRole("button", { name: "Create a workspace" }));
    fireEvent.change(screen.getByLabelText("Name of the business area"), { target: { value: "Hospital staffing" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains/9/overview");
    const post = vi.mocked(apiFetch).mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "POST")!;
    expect(post[0]).toBe("/api/domain/");
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ name: "Hospital staffing" });
  });

  it("offers no create button to an account that cannot edit domains", async () => {
    access.capabilities = [];
    mount();
    await screen.findByRole("link", { name: /Fleet/ });
    expect(screen.queryByRole("button", { name: "Create a workspace" })).not.toBeInTheDocument();
  });
});
