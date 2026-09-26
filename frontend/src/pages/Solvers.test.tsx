import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Solvers from "./Solvers";
import { ToastProvider } from "../components/ToastProvider";
import type { SolverInfo, SolverLicence } from "../api/v1";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const HIGHS: SolverInfo = { name: "highs", available: true, classes: ["LP", "MILP"], note: "HiGHS", origin: "built-in", automatic: true, licence: "not needed" };
const CBC: SolverInfo = {
  name: "cbc", available: true, classes: ["IP", "LP", "MILP"], note: "COIN-OR CBC", origin: "adapter", automatic: false,
  licence: "not needed", kind: "ortools-engine", version: "2.10", proves: "global", conformance: null,
};
const DEMO: SolverInfo = {
  name: "licensed-demo", available: true, classes: ["IP"], note: "a stand-in", origin: "adapter", automatic: false,
  licence: "missing", kind: "command-line", version: "1", proves: "global",
  conformance: { passed: true, version: "0", current: false, ran_at: "2026-09-26T08:00:00Z", ran_by: "admin", failed: [], notes: [] },
};
const DEMO_LICENCE: SolverLicence = { adapter: "licensed-demo", required: true, env: ["DEMO_LICENCE_KEY"], file: true, set: false };

let solvers: SolverInfo[] = [];
let licences: SolverLicence[] = [];
let skipped: { folder: string; reason: string }[] = [];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <Solvers />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  solvers = [HIGHS, CBC, DEMO];
  licences = [DEMO_LICENCE];
  skipped = [];
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path: string, options: RequestInit = {}) => {
    const method = options.method ?? "GET";
    if (path === "/api/v1/solvers") return { items: solvers, total: solvers.length, skipped };
    if (path === "/api/v1/solver-licences" && method === "GET") return { items: licences };
    if (path === "/api/v1/solver-licences/licensed-demo" && method === "PUT") {
      licences = [{ ...DEMO_LICENCE, set: true, fingerprint: "fa365ee4fd67", set_by: "admin", set_at: "2026-09-26T09:00:00Z" }];
      solvers = [HIGHS, CBC, { ...DEMO, licence: "set" }];
      return { adapter: "licensed-demo", set: true, fingerprint: "fa365ee4fd67" };
    }
    if (path === "/api/v1/solvers/cbc/conformance" && method === "POST") {
      solvers = [HIGHS, { ...CBC, automatic: true }, DEMO];
      return {
        adapter: "cbc", version: "2.10", passed: true,
        checks: [{ check: "answer:knapsack", result: "pass", detail: "optimal 17" }, { check: "stop", result: "note", detail: "ran 8 s" }],
      };
    }
    throw new Error(`unexpected ${method} ${path}`);
  });
});

describe("Solvers", () => {
  it("lists built-in and added solvers, and what each may do", async () => {
    renderPage();
    const cbc = await screen.findByTestId("solver-cbc");
    expect(within(cbc).getByText("added (ortools-engine 2.10)")).toBeInTheDocument();
    expect(within(cbc).getByText("only when named")).toBeInTheDocument();
    expect(within(cbc).getByText("not run")).toBeInTheDocument();
    const highs = screen.getByTestId("solver-highs");
    expect(within(highs).getByText("built in", { selector: "td" })).toBeInTheDocument();
    expect(within(highs).queryByRole("button")).not.toBeInTheDocument();
    const demo = screen.getByTestId("solver-licensed-demo");
    expect(within(demo).getByText("needed, not set")).toBeInTheDocument();
    expect(within(demo).getByText("run on 0, not this version")).toBeInTheDocument();
  });

  it("sends a licence once and never shows it", async () => {
    renderPage();
    const demo = await screen.findByTestId("solver-licensed-demo");
    fireEvent.click(within(demo).getByRole("button", { name: "Set licence" }));
    const form = await screen.findByRole("form", { name: "Licence for licensed-demo" });
    const key = within(form).getByLabelText("DEMO_LICENCE_KEY");
    expect(key).toHaveAttribute("type", "password");
    fireEvent.change(key, { target: { value: "DEMO-secret-value" } });
    fireEvent.change(within(form).getByLabelText("Licence file"), { target: { value: "demo licence\n" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save licence" }));

    await waitFor(() => expect(screen.getByText("set (fa365ee4fd67)")).toBeInTheDocument());
    const put = mockFetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
    expect(JSON.parse(String(put[1].body))).toEqual({ env: { DEMO_LICENCE_KEY: "DEMO-secret-value" }, file: "demo licence\n" });
    expect(screen.queryByRole("form", { name: "Licence for licensed-demo" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("DEMO-secret-value");
  });

  it("runs the conformance kit and shows its report", async () => {
    renderPage();
    const cbc = await screen.findByTestId("solver-cbc");
    fireEvent.click(within(cbc).getByRole("button", { name: "Run conformance kit" }));
    const report = await screen.findByRole("status", { name: "Conformance report" });
    expect(report).toHaveTextContent("cbc 2.10: passed");
    expect(report).toHaveTextContent("answer:knapsack optimal 17");
    // Passed: the rules may now choose it unasked.
    await waitFor(() => expect(within(screen.getByTestId("solver-cbc")).queryByText("only when named")).not.toBeInTheDocument());
  });

  it("says which manifests were not loaded, and why", async () => {
    skipped = [{ folder: "/opt/solver/adapters/broken", reason: "`proves` must say what its `optimal` means" }];
    renderPage();
    const alert = await screen.findByRole("alert", { name: "Manifests not loaded" });
    expect(alert).toHaveTextContent("/opt/solver/adapters/broken");
    expect(alert).toHaveTextContent("`proves` must say");
  });
});
