import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { CopyMapData } from "./CopyMapData";

describe("copying map data into another workspace", () => {
  it("copies it as it is and links to the copy", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => String(path).startsWith("/api/domain/")
      ? { items: [{ id: 1, name: "Camp A" }, { id: 2, name: "Camp B" }], total: 2 } : { id: 31, domain_id: 2 });
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
      <CopyMapData datasetId={30} fromDomain={1} name="camp.dxf" /></MemoryRouter></QueryClientProvider>);
    const into = await screen.findByLabelText("Copy into workspace");
    expect(Array.from((into as HTMLSelectElement).options).map((o) => o.text)).toEqual(["Copy into…", "Camp B"]);
    fireEvent.change(into, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByRole("link", { name: "Copied: open it" })).toHaveAttribute("href", "/domains/2/map-data/31");
    const call = vi.mocked(apiFetch).mock.calls.find(([p]) => p === "/api/v1/gis/datasets/30/copy")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({ domain_id: 2, name: "camp.dxf" });
  });
});
