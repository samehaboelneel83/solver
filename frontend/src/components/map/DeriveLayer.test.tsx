import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DeriveLayer from "./DeriveLayer";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function answer(url: string, init?: RequestInit) {
  if (url.includes("/entity-types")) return reply({ items: [{ id: 1, name: "base" }, { id: 2, name: "town" }], total: 2, limit: 500, offset: 0 });
  if (url.includes("/parameters")) return reply({ items: [{ id: 9, name: "within_30", index_type_ids: [1, 2] },
    { id: 8, name: "cost", index_type_ids: [1] }], total: 2, limit: 500, offset: 0 });
  if (url.includes("/derived-layers") && init?.method === "POST") return reply({ id: 44, name: "served", made: 3, layers: [] }, 201);
  return reply({});
}

afterEach(() => vi.restoreAllMocks());

describe("making a map layer from records (benchmark round 5)", () => {
  it("draws the places the chosen ones reach, by their 0/1 data", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((u, init) => Promise.resolve(answer(String(u), init)));
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
      <DeriveLayer domainId={7} kind="base" keys={["B1", "B4"]} />
    </MemoryRouter></QueryClientProvider>);
    expect(screen.getByText("From the 2 chosen base")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What to draw"), { target: { value: "service_area" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "within_30" })).toBeTruthy());
    expect(screen.queryByRole("option", { name: "cost" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make the layer" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/Made served: 3 shapes/));
    const sent = fetchSpy.mock.calls.find(([u]) => String(u).includes("/derived-layers"))!;
    expect(JSON.parse(String(sent[1]!.body))).toEqual({ domain_id: 7, name: "served by each base", how: "service_area",
      entity_type_id: 1, parameter_id: 9, keys: ["B1", "B4"] });
  });
});
