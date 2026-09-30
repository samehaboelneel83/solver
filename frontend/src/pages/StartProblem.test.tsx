import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SheetProposal } from "../api/v1";
import StartProblem from "./StartProblem";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { ApiError, apiFetch } from "../api/client";

const proposal = (): SheetProposal => ({
  kinds: [
    { sheet: "Teams", name: "team", key: "Code", rows: 2, exists: false, skip: false,
      fields: [{ column: "Name", name: "name", data_type: "text", enum_values: null, samples: ["Operations"], skip: false }], links: [] },
    { sheet: "Employees", name: "employee", key: "ID", rows: 4, exists: false, skip: false,
      fields: [{ column: "Hours", name: "hours", data_type: "integer", enum_values: null, samples: ["40", "20"], skip: false }],
      links: [{ column: "Team", name: "team", to: "team", skip: false }] },
  ],
});
let importBody: FormData | null;
let importFails: boolean;

function Landed() {
  return <p>problem {useParams().problemId}</p>;
}

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/domains/7/start"]}><Routes>
      <Route path="domains/:domainId/start" element={<StartProblem />} />
      <Route path="domains/:domainId/problems/:problemId" element={<Landed />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

describe("start a problem", () => {
  beforeEach(() => {
    importBody = null;
    importFails = false;
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path, options) => {
      if (path === "/api/v1/me") return { username: "modeller", capabilities: ["domain.edit", "model.publish"] };
      if (path.startsWith("/api/template/")) return { items: [{ id: 3, name: "feed_blend" }, { id: 4, name: "odd_one" }], total: 2 };
      if (path === "/api/v1/templates/3/apply") return { problem_id: 31, domain_id: 7, template_id: 3, model_version_id: 1, scenario_id: 1 };
      if (path === "/api/problem/") return { id: 42, domain_id: 7, name: JSON.parse(String(options?.body)).name };
      if (path === "/api/v1/domains/7/spreadsheet/propose") return proposal();
      if (path === "/api/v1/domains/7/spreadsheet/import") {
        importBody = options?.body as FormData;
        if (importFails) {
          throw new ApiError(422, JSON.stringify({ detail: { message: "Nothing was imported", faults: ["'Employees' row 3, column 'Hours': 'forty' is not a whole number"], more: 0 } }));
        }
        return { made: { kinds: 2, fields: 2, records: 6, link_types: 1, links: 4 } };
      }
      throw new Error(`Unexpected ${path}`);
    });
  });

  it("starts from a ready example in plain words, named as the person says", async () => {
    mount();
    expect(await screen.findByRole("heading", { name: "Cheapest feed blend" })).toBeInTheDocument();
    expect(screen.getByText(/Mix 100 kg of feed/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "odd one" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/What is it called/), { target: { value: "Pig feed" } });
    fireEvent.click(within(screen.getByRole("heading", { name: "Cheapest feed blend" }).closest("li")!).getByRole("button", { name: "Use this example" }));
    expect(await screen.findByText("problem 31")).toBeInTheDocument();
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/api/v1/templates/3/apply",
      expect.objectContaining({ body: JSON.stringify({ domain_id: 7, name: "Pig feed" }) }));
  });

  it("starts from scratch once it has a name", async () => {
    mount();
    fireEvent.click(screen.getByRole("radio", { name: /From scratch/ }));
    const make = screen.getByRole("button", { name: "Make the problem" });
    expect(make).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/What is it called/), { target: { value: "Rota" } });
    fireEvent.click(make);
    expect(await screen.findByText("problem 42")).toBeInTheDocument();
  });

  it("reads a spreadsheet, lets the person correct it, then imports it and makes the problem", async () => {
    mount();
    fireEvent.click(screen.getByRole("radio", { name: /From a spreadsheet/ }));
    fireEvent.change(screen.getByLabelText(/What is it called/), { target: { value: "Staffing" } });
    const file = new File(["x"], "staff.xlsx");
    fireEvent.change(screen.getByLabelText(/An Excel workbook/), { target: { files: [file] } });
    const employees = await screen.findByRole("article", { name: "Sheet Employees" });
    expect(within(employees).getByText(/a link to a/)).toHaveTextContent("a link to a team");
    fireEvent.change(within(employees).getByLabelText("Type of Hours"), { target: { value: "number" } });
    fireEvent.change(within(employees).getByLabelText("Link name for Team"), { target: { value: "works_in" } });
    fireEvent.click(within(screen.getByRole("article", { name: "Sheet Teams" })).getByLabelText("Import Name"));

    fireEvent.click(screen.getByRole("button", { name: "Import and make the problem" }));
    expect(await screen.findByText("problem 42")).toBeInTheDocument();
    const sent = JSON.parse(String(importBody!.get("proposal"))) as SheetProposal;
    expect(sent.kinds[1].fields[0].data_type).toBe("number");
    expect(sent.kinds[1].links[0].name).toBe("works_in");
    expect(sent.kinds[0].fields[0].skip).toBe(true);
    expect(importBody!.get("file")).toBe(file);
  });

  it("shows every cell an import refused and makes no problem", async () => {
    importFails = true;
    mount();
    fireEvent.click(screen.getByRole("radio", { name: /From a spreadsheet/ }));
    fireEvent.change(screen.getByLabelText(/What is it called/), { target: { value: "Staffing" } });
    fireEvent.change(screen.getByLabelText(/An Excel workbook/), { target: { files: [new File(["x"], "staff.xlsx")] } });
    fireEvent.click(await screen.findByRole("button", { name: "Import and make the problem" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("'Employees' row 3, column 'Hours': 'forty' is not a whole number");
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path]) => path === "/api/problem/")).toBe(false));
  });
});
