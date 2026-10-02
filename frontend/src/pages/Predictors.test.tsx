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

const TRAINING = { id: 9, domain_id: 7, state: "done", predictor_id: 3, error: null, seconds: 2,
  request: { name: "sales_model", entity_type: "product", target: "demand", kind: "random_forest" } };

function stub(write = vi.fn().mockResolvedValue(TRAINED), capabilities = ["domain.edit"], items: unknown[] = [TRAINED],
  training: unknown = TRAINING) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") return write(path, options);
    if (path.startsWith("/api/v1/predictor-trainings/")) return Promise.resolve(typeof training === "function" ? training() : training);
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
  const write = stub(vi.fn().mockResolvedValue({ training_id: 9, state: "running" }));
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
  // In the background (operator trial F31): answered at once, then asked after.
  expect(path).toBe("/api/v1/predictors/train?background=true");
  expect(JSON.parse(options.body)).toEqual({
    domain_id: 7, name: "sales_model", entity_type: "product", target: "demand", features: ["price", "promo"],
    kind: "random_forest", trees: 50, max_depth: 6,
  });
  expect(await screen.findByText("Trained sales_model.")).toBeInTheDocument();
  expect(mockFetch.mock.calls.some(([p]) => p === "/api/v1/predictor-trainings/9")).toBe(true);
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

const CHURN = {
  ...TRAINED, id: 4, name: "churn_model", note: null, inputs: ["price"],
  metrics: {
    rows: 100, rows_skipped: 0, holdout_rows: 20, evaluated_on: "a held-out 20% of the rows",
    positive: "true", negative: "false", predicts: "the probability that loyal is true", accuracy: 0.9, auc: 0.95, brier: 0.071,
  },
  training: { kind: "random_forest_classifier", entity_type: "product", features: ["price"], target: "loyal", positive: "true" },
};

it("shows a yes-or-no model by how often it is right, and a forest by how often its range held", async () => {
  const withRange = { ...TRAINED, metrics: { ...TRAINED.metrics, interval: "10th to 90th percentile of the trees", interval_coverage: 0.78 } };
  stub(undefined, undefined, [withRange, CHURN]);
  renderPage();
  const [forest, churn] = await screen.findAllByTestId("predictor");
  expect(within(forest).getByText(/78% of held-out values fell between their 10th to 90th percentile/)).toBeInTheDocument();
  expect(within(churn).getByText(/Random forest \(yes or no\) on product, predicting the probability that loyal is true/)).toBeInTheDocument();
  const scores = within(churn).getByLabelText("How well churn_model predicts");
  expect(scores).toHaveTextContent("Right90%");
  expect(scores).toHaveTextContent("AUC0.95");
  expect(scores).not.toHaveTextContent("R²");
});

it("trains a yes-or-no model on a two-valued attribute, naming which value is yes", async () => {
  const write = stub();
  renderPage();
  await screen.findByTestId("predictor");
  fireEvent.change(screen.getByLabelText("Name of the model"), { target: { value: "label_model" } });
  fireEvent.change(screen.getByLabelText("Learn from records of"), { target: { value: "product" } });
  fireEvent.change(screen.getByLabelText("Method"), { target: { value: "random_forest_classifier" } });
  const predict = screen.getByLabelText("Predict") as HTMLSelectElement;
  // Text and whole numbers can hold two values; plain numbers are not offered.
  expect(Array.from(predict.options).map((o) => o.value)).toEqual(["", "promo", "label"]);
  fireEvent.change(predict, { target: { value: "label" } });
  fireEvent.change(screen.getByLabelText("Counts as yes"), { target: { value: "premium" } });
  fireEvent.click(screen.getByLabelText("price"));
  fireEvent.click(screen.getByRole("button", { name: "Train" }));
  await waitFor(() => expect(write).toHaveBeenCalled());
  expect(JSON.parse(write.mock.calls[0][1].body)).toEqual(expect.objectContaining({
    kind: "random_forest_classifier", target: "label", positive: "premium", features: ["price"],
  }));
});

it("says why a training failed on the server, after the request was answered (operator trial F31)", async () => {
  let state = "running";
  stub(vi.fn().mockResolvedValue({ training_id: 9, state: "running" }), ["domain.edit"], [TRAINED],
    () => ({ ...TRAINING, state, seconds: 4, predictor_id: null, error: state === "failed" ? "the target has 0 rows with a value" : null }));
  renderPage();
  await screen.findByTestId("predictor");
  fireEvent.change(screen.getByLabelText("Name of the model"), { target: { value: "sales_model" } });
  fireEvent.change(screen.getByLabelText("Learn from records of"), { target: { value: "product" } });
  fireEvent.change(screen.getByLabelText("Predict"), { target: { value: "demand" } });
  fireEvent.click(screen.getByLabelText("price"));
  fireEvent.click(screen.getByRole("button", { name: "Train" }));
  expect(await screen.findByText(/goes on on the server if you leave/)).toHaveTextContent("Training for 4 s");
  state = "failed";
  expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent("0 rows with a value");
});

it("makes number fields from a text, and keeps a model's predictions as data (benchmark, October 2026)", async () => {
  const write = stub(vi.fn().mockImplementation((path: string) => Promise.resolve(path.endsWith("/derive")
    ? { made: ["label_a", "label_b"], records: 10, left_empty: 0 }
    : { field: "demand_forecast", entity_type: "product", written: 7, skipped: [], skipped_count: 0 })));
  renderPage();
  const card = await screen.findByTestId("predictor");
  await screen.findAllByRole("option", { name: "product" });
  fireEvent.change(screen.getByLabelText("Learn from records of"), { target: { value: "product" } });
  fireEvent.click(screen.getByRole("button", { name: "one yes/no field per value" }));
  expect(await screen.findByText(/Made label_a, label_b on 10 records/)).toBeInTheDocument();
  expect(write.mock.calls[0][0]).toBe("/api/v1/entity-types/5/derive");
  expect(JSON.parse(write.mock.calls[0][1].body)).toEqual({ op: "categories", field: "label" });

  expect(within(card).getByLabelText("Field for the predictions")).toHaveValue("demand_forecast");
  fireEvent.click(within(card).getByRole("button", { name: "Predict and keep" }));
  expect(await within(card).findByText(/7 product records now have demand_forecast/)).toBeInTheDocument();
  expect(JSON.parse(write.mock.calls[1][1].body)).toEqual({ field: "demand_forecast", only_missing: true });
});

it("keeps one prediction per record and period, an input held at a number (benchmark re-test, October 2026)", async () => {
  ENTITY_TYPES.items.push({ id: 6, domain_id: 7, name: "week", role: "time", colour: null, icon: null, attributes: [] } as never);
  const write = stub(vi.fn().mockResolvedValue({ parameter: "demand_forecast", parameter_id: 40, written: 14, skipped: [], skipped_count: 0 }));
  renderPage();
  const card = await screen.findByTestId("predictor");
  await within(card).findAllByRole("option", { name: "week" });
  fireEvent.change(within(card).getByLabelText("One prediction per"), { target: { value: "week" } });
  fireEvent.change(within(card).getByLabelText("Input each period feeds"), { target: { value: "promo" } });
  fireEvent.change(within(card).getByLabelText("price comes from"), { target: { value: "#" } });
  fireEvent.change(within(card).getByLabelText("price held at"), { target: { value: "9.5" } });
  fireEvent.click(within(card).getByRole("button", { name: "Predict and keep" }));
  expect(await within(card).findByText(/14 predictions kept as the data value demand_forecast\[product, week\]/)).toBeInTheDocument();
  expect(JSON.parse(write.mock.calls.at(-1)![1].body)).toEqual({ field: "demand_forecast", only_missing: false,
    inputs: { price: 9.5 }, over: { kind: "week", feature: "promo" } });
  ENTITY_TYPES.items.pop();
});
