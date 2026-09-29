import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { DomainRouteProvider } from "../hooks/useDomain";
import Predictors from "./Predictors";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const TRAINED = {
  id: 3, domain_id: 7, name: "demand_model", note: "weekly demand", inputs: ["price", "promo"],
  metrics: { rows: 120, rows_skipped: 4, holdout_rows: 24, evaluated_on: "a held-out 20% of the rows", r2: 0.8123, mae: 2.5, rmse: 3.25 },
  training: { kind: "random_forest", entity_type: "product", features: ["price", "promo"], target: "demand" },
  summary: { inputs: 2, trees: 50, nodes: 900, leaves: 450, aggregation: "mean" },
  created_at: "2026-09-28T10:00:00Z", updated_at: "2026-09-28T10:00:00Z",
};
const ENTITY_TYPES = {
  items: [{
    id: 5, domain_id: 7, name: "product", role: "resource", colour: null, icon: null,
    attributes: [
      { id: 1, entity_type_id: 5, name: "price", data_type: "number" },
      { id: 2, entity_type_id: 5, name: "promo", data_type: "integer" },
      { id: 3, entity_type_id: 5, name: "demand", data_type: "number" },
      { id: 4, entity_type_id: 5, name: "label", data_type: "text" },
    ],
  }],
  total: 1,
};

function stub(write = vi.fn().mockResolvedValue(TRAINED), capabilities = ["domain.edit"], items: unknown[] = [TRAINED]) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") return write(path, options);
    if (path.startsWith("/api/v1/predictors")) return Promise.resolve({ items, total: items.length });
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(ENTITY_TYPES);
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  return write;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/domains/7/data/predictors"]}>
        <Routes>
          <Route path="/domains/:domainId/data/predictors" element={<DomainRouteProvider><Predictors /></DomainRouteProvider>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

it("lists a domain's predictors with how a rule reads them and how well they predict", async () => {
  stub();
  renderPage();
  const card = await screen.findByTestId("predictor");
  expect(within(card).getByText("predict demand_model(price, promo)")).toBeInTheDocument();
  expect(within(card).getByText(/Random forest on product, predicting demand/)).toBeInTheDocument();
  const scores = within(card).getByLabelText("How well demand_model predicts");
  expect(scores).toHaveTextContent("R²0.812");
  expect(scores).toHaveTextContent("Mean error2.5");
  expect(within(card).getByText(/120 rows, 4 skipped/)).toBeInTheDocument();
  expect(mockFetch.mock.calls.some(([p]) => p === "/api/v1/predictors?domain_id=7&limit=200")).toBe(true);
});

it("trains a model from numeric attributes of a record type", async () => {
  const write = stub();
  renderPage();
  await screen.findByTestId("predictor");
  fireEvent.change(screen.getByLabelText("Name of the model"), { target: { value: "sales_model" } });
  fireEvent.change(screen.getByLabelText("Learn from records of"), { target: { value: "product" } });
  // Only numeric attributes are offered: `label` is text.
  const predict = screen.getByLabelText("Predict") as HTMLSelectElement;
  expect(Array.from(predict.options).map((o) => o.value)).toEqual(["", "price", "promo", "demand"]);
  fireEvent.change(predict, { target: { value: "demand" } });
  fireEvent.click(screen.getByLabelText("price"));
  fireEvent.click(screen.getByLabelText("promo"));
  expect(screen.queryByLabelText("demand")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Train" }));
  await waitFor(() => expect(write).toHaveBeenCalled());
  const [path, options] = write.mock.calls[0];
  expect(path).toBe("/api/v1/predictors/train");
  expect(JSON.parse(options.body)).toEqual({
    domain_id: 7, name: "sales_model", entity_type: "product", target: "demand", features: ["price", "promo"],
    kind: "random_forest", trees: 50, max_depth: 6,
  });
  expect(await screen.findByText("Trained demand_model.")).toBeInTheDocument();
});

it("says why a delete was refused, and asks first", async () => {
  const write = stub(vi.fn().mockRejectedValue(new Error("demand_model is read by model version 4; it cannot be deleted")));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Delete demand_model" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete it" }));
  await waitFor(() => expect(write).toHaveBeenCalledWith("/api/v1/predictors/3", expect.objectContaining({ method: "DELETE" })));
  expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be deleted/);
});

it("offers no training, upload or delete without domain.edit, and explains an empty list", async () => {
  stub(vi.fn(), [], []);
  renderPage();
  expect(await screen.findByText(/No predictors yet\./)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Train" })).toBeNull();
  expect(screen.queryByText("Upload a model")).toBeNull();
});
