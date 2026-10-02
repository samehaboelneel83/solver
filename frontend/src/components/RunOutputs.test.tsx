import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import RunOutputs from "./RunOutputs";

vi.mock("../hooks/useDomain", () => ({ useDomain: () => ({ domainId: 1, setDomainId: () => {} }) }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

const ANSWER = { layers: [{ id: "ship", kind: "links", title: "ship: 1 links" }], features: [
  { type: "Feature", geometry: { type: "LineString", coordinates: [[30, 31.2], [30.01, 31.2]] },
    properties: { layer: "ship", set: "depot-store", key: "a|b", value: 4, status: "chosen", title: "ship: a → b" } }] };

it("shows map data under the answer and draws the flows along its roads (benchmark, October 2026)", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    const p = String(path);
    if (p.includes("/answer-map")) return ANSWER as never;
    if (p.endsWith("/features")) return { type: "FeatureCollection", truncated: false, features: [
      { type: "Feature", geometry: { type: "LineString", coordinates: [[30, 31.2], [30, 31.21], [30.01, 31.21]] }, properties: { layer: "ROADS", kind: "line" } }] } as never;
    if (p.includes("/gis/datasets/5")) return { id: 5, name: "city roads", layers: [{ id: 1, name: "ROADS", kinds: { line: 1 } }] } as never;
    if (p.includes("/gis/datasets")) return { items: [{ id: 5, name: "city roads", layers: 1 }], postgis: false } as never;
    return {} as never;
  });
  render(<QueryClientProvider client={new QueryClient()}><RunOutputs runId={9} status="optimal" /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("Show under the answer"), { target: { value: "5" } });
  fireEvent.change(await screen.findByLabelText("Draw flows along"), { target: { value: "ROADS" } });
  await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.map(([p]) => String(p)))
    .toContain("/api/v1/runs/9/answer-map?along_dataset=5&along_layer=ROADS"));
  expect(screen.getByText("ROADS (city roads, under the answer)")).toBeInTheDocument();
});
