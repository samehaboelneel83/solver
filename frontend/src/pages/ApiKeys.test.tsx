import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApiKeys from "./ApiKeys";
import { ToastProvider } from "../components/ToastProvider";
import type { ApiKey } from "../api/v1";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const KEY: ApiKey = {
  id: "k1",
  name: "nightly import",
  prefix: "0123456789ab",
  user_id: "u1",
  username: "admin",
  capabilities: ["run.submit"],
  created_at: "2026-09-22T10:00:00Z",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
};

let keys: ApiKey[] = [];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <ApiKeys />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  keys = [];
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path: string, options: RequestInit = {}) => {
    if (path === "/api/v1/me") return { username: "admin", display_name: null, capabilities: ["model.publish", "run.submit"] };
    if (path === "/api/v1/api-keys" && (options.method ?? "GET") === "GET") return { items: keys };
    if (path === "/api/v1/api-keys" && options.method === "POST") {
      const body = JSON.parse(String(options.body));
      const made = { ...KEY, name: body.name, capabilities: body.capabilities };
      keys = [made];
      return { ...made, token: "sk_0123456789ab_the-secret" };
    }
    if (path === "/api/v1/api-keys/k1" && options.method === "DELETE") {
      keys = [{ ...KEY, revoked_at: "2026-09-22T11:00:00Z" }];
      return undefined;
    }
    throw new Error(`unexpected ${options.method ?? "GET"} ${path}`);
  });
});

describe("API keys", () => {
  it("offers the caller's own capabilities, all ticked", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("run.submit")).toBeChecked());
    expect(screen.getByLabelText("model.publish")).toBeChecked();
    expect(screen.getByText("No keys yet.")).toBeInTheDocument();
  });

  it("makes a key with what was ticked, and shows its token once", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("model.publish")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "nightly import" } });
    fireEvent.click(screen.getByLabelText("model.publish"));
    fireEvent.click(screen.getByRole("button", { name: "Make key" }));

    await waitFor(() => expect(screen.getByTestId("api-key-token")).toHaveTextContent("sk_0123456789ab_the-secret"));
    const post = mockFetch.mock.calls.find((call) => call[1]?.method === "POST")!;
    expect(JSON.parse(String(post[1].body))).toEqual({
      name: "nightly import",
      capabilities: ["run.submit"],
      expires_in_days: 90,
    });
    expect(screen.getByText(/will not be shown again/)).toBeInTheDocument();

    // The list shows the key by its prefix, never its token.
    const table = await screen.findByRole("table");
    expect(within(table).getByText("sk_0123456789ab_…")).toBeInTheDocument();
    expect(within(table).queryByText(/the-secret/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("api-key-token")).not.toBeInTheDocument();
  });

  it("revokes a key after asking", async () => {
    keys = [KEY];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(screen.getByText("Revoked")).toBeInTheDocument());
    expect(mockFetch.mock.calls.some((call) => call[0] === "/api/v1/api-keys/k1" && call[1]?.method === "DELETE")).toBe(true);
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });
});
