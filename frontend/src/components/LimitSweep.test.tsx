import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LimitSweep, { gains, sweepValues } from "./LimitSweep";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

describe("the values a sweep tries", () => {
  it("spreads them evenly, at most eight", () => {
    expect(sweepValues(40000, 80000, 5)).toEqual([40000, 50000, 60000, 70000, 80000]);
    expect(sweepValues(1, 2, 3)).toEqual([1, 1.5, 2]);
    expect(sweepValues(0, 70, 20)).toHaveLength(8);
    expect(sweepValues(5, 10, 1)).toEqual([]);
  });

  it("says what each step bought per unit", () => {
    expect(gains([{ value: 40, goal: 100 }, { value: 60, goal: 140 }, { value: 80, goal: null }])).toEqual([null, 2, null]);
  });
});

it("solves the model once per value, each kept as a scenario, and tabulates the goal", async () => {
  const posts: [string, unknown][] = [];
  let next = 100;
  vi.mocked(apiFetch).mockImplementation((async (path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === "POST") {
      const body = JSON.parse(init.body ?? "{}");
      posts.push([path, body]);
      return path.endsWith("/runs") ? { id: next++, status: "queued" } : { id: posts.length, ...body };
    }
    if (path.startsWith("/api/v1/versions/")) {
      return { id: 3, ir: { constraints: [{ id: "budget", left: { sum: {} }, relation: "<=", right: { const: 60000 } }] } };
    }
    const run = Number(path.split("/").pop());
    return { id: run, status: "optimal", objective: 1000 + (run - 100) * 50 };
  }) as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LimitSweep problemId={9} versionId={3} scenarioHref={(s, r) => `/runs?scenario=${s}&run=${r}`} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(await screen.findByLabelText("From"), { target: { value: "40000" } });
  fireEvent.change(screen.getByLabelText("To"), { target: { value: "80000" } });
  fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Solve 3 times" }));
  await waitFor(() => expect(posts.filter(([p]) => p.endsWith("/runs"))).toHaveLength(3));
  expect(posts[0]).toEqual(["/api/v1/scenarios", { problem_id: 9, model_version_id: 3, name: "budget = 40,000", patch: { set_limit: { budget: 40000 } } }]);
  const table = await screen.findByRole("table", { name: "Goal at each limit" });
  await waitFor(() => expect(within(table).getByText("1,100")).toBeInTheDocument());
  // 50 more for each 20,000 more.
  expect(within(table).getAllByText("0.003")).toHaveLength(2);
  expect(screen.getByRole("img", { name: /The goal as budget's limit goes from 40,000 to 80,000/ })).toBeInTheDocument();
});
