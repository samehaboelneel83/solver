import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
const chosen = { id: null as number | null };
vi.mock("../hooks/useDomain", () => ({ useDomain: () => ({ domainId: chosen.id, setDomainId: vi.fn() }) }));
import { apiFetch } from "../api/client";
import { LegacyDomainRedirect, LegacyProblemRedirect } from "./LegacyRedirect";

function Landed() {
  const { pathname, search, hash } = useLocation();
  return <p data-testid="landed">{`${pathname}${search}${hash}`}</p>;
}

function mount(path: string) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="runs" element={<LegacyProblemRedirect page="runs" fallback={<p>old runs page</p>} />} />
      <Route path="workspace" element={<LegacyProblemRedirect page="workspace" fallback={<p>old workspace</p>} />} />
      <Route path="model" element={<LegacyProblemRedirect page="model" fallback={<p>old model page</p>} />} />
      <Route path="parameters" element={<LegacyDomainRedirect page="parameters" fallback={<p>old parameters page</p>} />} />
      <Route path="entities/:id" element={<LegacyDomainRedirect page="entities" fallback={<p>old record</p>} />} />
      <Route path="data" element={<LegacyDomainRedirect page="data" />} />
      <Route path="domains/*" element={<Landed />} />
      <Route path="domains" element={<Landed />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

describe("old links land on their scoped page in one step", () => {
  beforeEach(() => {
    chosen.id = null;
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      if (path === "/api/problem/9") return { id: 9, domain_id: 7 };
      if (path === "/api/problem/404") throw new ApiError(404, "not found");
      throw new Error(`Unexpected ${path}`);
    });
  });

  it("a run link keeps the rest of the query and the hash", async () => {
    mount("/runs?problem=9&run=12&tab=guided#rules");
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains/7/problems/9/runs/12?tab=guided#rules");
  });

  it("the guided workspace opens the runs page on its guided tab", async () => {
    mount("/workspace?problem=9");
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains/7/problems/9/runs?tab=guided");
  });

  it("with no problem in the link, the old page still opens with its pickers", () => {
    mount("/model");
    expect(screen.getByText("old model page")).toBeInTheDocument();
  });

  it("a problem that is gone says so and offers the way back", async () => {
    mount("/model?problem=404");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The linked problem could not be found.");
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose a domain" })).toHaveAttribute("href", "/domains");
  });

  it("a domain page goes to the domain in the link, else the one chosen last", async () => {
    mount("/parameters?domain=3&parameter=5");
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains/3/data/parameters?parameter=5");
  });

  it("a record link keeps its id", async () => {
    chosen.id = 4;
    mount("/entities/88");
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains/4/data/records/88");
  });

  it("a hub with no domain goes to the chooser, which comes back to it", async () => {
    mount("/data");
    expect(await screen.findByTestId("landed")).toHaveTextContent("/domains?next=data");
  });

  it("a domain page with no domain at all keeps the old page", () => {
    mount("/parameters");
    expect(screen.getByText("old parameters page")).toBeInTheDocument();
  });
});
