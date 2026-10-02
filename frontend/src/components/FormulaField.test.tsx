import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import FormulaField from "./FormulaField";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

const KIND = { id: 4, domain_id: 1, name: "road", role: "location", colour: null, icon: null,
  attributes: [{ id: 1, name: "volume", data_type: "number" }, { id: 2, name: "capacity", data_type: "integer" }] } as never;

it("computes a ratio of a record's fields into a field of its own (benchmark, October 2026)", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ made: ["vc_ratio"], records: 40, left_empty: 2 } as never);
  render(<QueryClientProvider client={new QueryClient()}><FormulaField kind={KIND} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Name of the computed field"), { target: { value: "vc_ratio" } });
  fireEvent.change(screen.getByLabelText("Formula"), { target: { value: "volume / capacity" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(await screen.findByText(/vc_ratio computed on 40 records; 2 left empty/)).toBeInTheDocument();
  const [path, init] = vi.mocked(apiFetch).mock.calls[0];
  expect(path).toBe("/api/v1/entity-types/4/derive");
  expect(JSON.parse(String((init as RequestInit).body))).toEqual({ op: "formula", field: "vc_ratio", formula: "volume / capacity" });
});
