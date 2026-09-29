import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import NavigationHub, { SourcesPage } from "./NavigationHub";
import { apiFetch } from "../api/client";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
const access = vi.hoisted(() => ({ capabilities: ["integration.run"], known: true }));
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ known: access.known, can: (cap: string) => access.capabilities.includes(cap) }) }));

beforeEach(() => { vi.clearAllMocks(); access.capabilities = ["integration.run"]; });
function mount(page: JSX.Element, route = "/domains/7/problems/9/inputs") {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[route]}><Routes>
      <Route path="/domains/:domainId/problems/:problemId/inputs" element={page} />
      <Route path="/domains/:domainId/data/sources" element={page} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

it("keeps input links in their domain and problem", () => {
  mount(<NavigationHub kind="inputs" />);
  expect(screen.getByRole("link", { name: /Scenario inputs/ })).toHaveAttribute("href", "/domains/7/problems/9/scenarios");
  expect(screen.getByRole("link", { name: /Records & relationships/ })).toHaveAttribute("href", "/domains/7/data");
});
it("does not fetch sources without the required capability", () => {
  access.capabilities = [];
  mount(<SourcesPage />, "/domains/7/data/sources");
  expect(screen.getByRole("alert")).toHaveTextContent("does not have access");
  expect(apiFetch).not.toHaveBeenCalled();
});
it("paginates configured sources in the current domain", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ items: [{ id: 1, name: "Warehouse", enabled: true }], total: 21 });
  mount(<SourcesPage />, "/domains/7/data/sources");
  await screen.findByText("Warehouse");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Page 2");
  expect(apiFetch).toHaveBeenCalledWith("/api/v1/connections?domain_id=7&limit=20&offset=20");
});
it("reports a source failure instead of claiming there are no sources", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new Error("Unavailable"));
  mount(<SourcesPage />, "/domains/7/data/sources");
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  expect(screen.queryByText("No configured sources on this page.")).not.toBeInTheDocument();
});
