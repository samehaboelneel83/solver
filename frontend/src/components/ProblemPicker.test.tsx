import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import ProblemPicker from "./ProblemPicker";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const FIRST = [{ id: 1, name: "alpha" }, { id: 2, name: "beta" }];

function mount(props: Partial<Parameters<typeof ProblemPicker>[0]> = {}) {
  const onChoose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProblemPicker domainId={7} current={FIRST[0]} firstPage={FIRST} total={2} onChoose={onChoose} {...props} />
    </QueryClientProvider>
  );
  return onChoose;
}

beforeEach(() => mockFetch.mockReset());

it("is a plain choice when every problem is on the first page", () => {
  const onChoose = mount();
  expect(screen.queryByLabelText("Find a problem")).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "2" } });
  expect(onChoose).toHaveBeenCalledWith("2");
  expect(mockFetch).not.toHaveBeenCalled();
});

it("searches the whole domain when it has more problems than the first page", async () => {
  mockFetch.mockResolvedValue({ items: [{ id: 812, name: "zeta rota" }], total: 1 });
  const onChoose = mount({ total: 900 });
  expect(screen.getByRole("status")).toHaveTextContent("Showing the first 2 of 900 problems");
  fireEvent.change(screen.getByLabelText("Find a problem"), { target: { value: "zeta" } });
  expect(await screen.findByRole("option", { name: "zeta rota" })).toBeInTheDocument();
  const [path] = mockFetch.mock.calls.at(-1)!;
  expect(path).toContain("q=zeta");
  expect(path).toContain("f_domain_id=7");
  expect(screen.getByRole("status")).toHaveTextContent("1 match.");
  // The chosen problem stays chosen while other matches are listed.
  expect(screen.getByLabelText("Problem")).toHaveValue("1");
  fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "812" } });
  expect(onChoose).toHaveBeenCalledWith("812");
});

it("says when nothing matches, and when matches run past one page", async () => {
  mockFetch.mockResolvedValueOnce({ items: [], total: 0 });
  mount({ total: 900 });
  fireEvent.change(screen.getByLabelText("Find a problem"), { target: { value: "nothing" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No problem matches “nothing”."));

  mockFetch.mockResolvedValueOnce({ items: FIRST, total: 120 });
  fireEvent.change(screen.getByLabelText("Find a problem"), { target: { value: "a" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Showing 2 of 120 matches"));
});
