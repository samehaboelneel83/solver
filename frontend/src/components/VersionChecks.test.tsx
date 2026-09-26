import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VersionChecks from "./VersionChecks";
import { ToastProvider } from "./ToastProvider";
import type { VersionChecks as Checks } from "../api/v1";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;
let checks: Checks;

function renderIt() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <VersionChecks versionId={5} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path: string, options: RequestInit = {}) => {
    if (path === "/api/v1/model-versions/5/checks") return checks;
    if (path === "/api/v1/model-versions/5/check" && options.method === "POST") {
      checks = { ...checks, state: "passed", cases: checks.cases.map((c) => ({ ...c, state: "passed", reasons: [] })) };
      return { ...checks, run_ids: [9] };
    }
    throw new Error(`unexpected ${path}`);
  });
});

describe("VersionChecks", () => {
  it("names each failed case and why", async () => {
    checks = { model_version_id: 5, state: "failed", cases: [
      { case_id: 1, name: "the usual blend", run_id: 3, state: "failed", reasons: ["the objective is 53.8, expected 43.5 within 4e-05"] }] };
    renderIt();
    expect(await screen.findByText("the usual blend")).toBeInTheDocument();
    expect(screen.getByText(/the objective is 53.8, expected 43.5/)).toBeInTheDocument();
  });

  it("marks a nightly regression in red", async () => {
    checks = {
      model_version_id: 5,
      state: "failed",
      cases: [{
        case_id: 1,
        name: "two shifts",
        run_id: 3,
        state: "failed",
        nightly_regressed: true,
        reasons: ["passed last night, fails tonight (the objective is 99, expected 2 within 2e-06)"],
      }],
    };
    renderIt();
    expect(await screen.findByText("regressed overnight")).toBeInTheDocument();
    expect(screen.getByText(/passed last night, fails tonight/)).toBeInTheDocument();
  });

  it("runs the checks and shows them passing", async () => {
    checks = { model_version_id: 5, state: "unchecked", cases: [{ case_id: 1, name: "two shifts", run_id: null, state: "unchecked", reasons: [] }] };
    renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "Run checks" }));
    await waitFor(() => expect(screen.getAllByText("Passed").length).toBe(2));
  });

  it("says a problem with no cases has no gate", async () => {
    checks = { model_version_id: 5, state: "no cases", cases: [] };
    renderIt();
    expect(await screen.findByText(/has no acceptance cases yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
