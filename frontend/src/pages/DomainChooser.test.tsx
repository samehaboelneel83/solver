import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import DomainChooser from "./DomainChooser";

function mount(path = "/domains") {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><DomainChooser /></MemoryRouter>
  </QueryClientProvider>);
}

describe("choosing a domain (Epic UX, U-1)", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
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
    fireEvent.change(screen.getByRole("searchbox", { name: "Search domains" }), { target: { value: "zzz" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No domains match"));
    expect(vi.mocked(apiFetch).mock.calls.some(([p]) => String(p).includes("q=zzz"))).toBe(true);
  });
});
