import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Settings from "./Settings";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

/**
 * The two things this screen must not get wrong.
 *
 * It must say **where each value came from**, because the whole point of
 * three levels is knowing which of them to edit; and clearing a box must
 * **unset** that level rather than write a zero, or overrides could only ever
 * accumulate.
 */

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const SETTINGS = {
  items: [
    {
      key: "solve.time_limit_s",
      value: 30,
      source: "domain",
      value_type: "number",
      description: "How long a solve may run",
    },
    {
      key: "solve.seed",
      value: 1,
      source: "default",
      value_type: "number",
      description: "Random seed",
    },
  ],
};

const PROBLEMS = { items: [{ id: 1, name: "weekly_rota", domain_id: 1 }], total: 1 };

function stub(overrides: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") {
      const write = overrides.write as
        | ((p: string, o?: { method?: string; body?: string }) => Promise<unknown>)
        | undefined;
      if (write) return write(path, options);
      return Promise.resolve({ ok: true });
    }
    if (path.startsWith("/api/v1/me")) {
      return Promise.resolve(
        overrides.me ?? { username: "admin", display_name: null, capabilities: ["settings.edit"] }
      );
    }
    if (path.startsWith("/api/v1/settings")) return Promise.resolve(overrides.settings ?? SETTINGS);
    if (path.startsWith("/api/problem")) return Promise.resolve(PROBLEMS);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/settings"]}>
          <Settings />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
  stub();
});

describe("Settings", () => {
  it("says which level supplied each value", async () => {
    renderPage();

    expect(await screen.findByText(/^set for this domain/i)).toBeInTheDocument();
    expect(screen.getByText(/^built-in default$/i)).toBeInTheDocument();
  });

  it("clearing a box unsets that level rather than writing a zero", async () => {
    const sent: unknown[] = [];
    stub({
      write: (_path: string, options?: { body?: string }) => {
        sent.push(JSON.parse(options?.body ?? "{}"));
        return Promise.resolve({ ok: true });
      },
    });
    renderPage();

    const box = await screen.findByLabelText("solve.time_limit_s");
    fireEvent.change(box, { target: { value: "" } });
    fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0]);

    await waitFor(() => expect(sent).toHaveLength(1));
    // null, not 0: unsetting restores the level above.
    expect(sent[0]).toMatchObject({ key: "solve.time_limit_s", value: null });
  });

  it("sends a number as a number, not as the text that was typed", async () => {
    const sent: unknown[] = [];
    stub({
      write: (_path: string, options?: { body?: string }) => {
        sent.push(JSON.parse(options?.body ?? "{}"));
        return Promise.resolve({ ok: true });
      },
    });
    renderPage();

    fireEvent.change(await screen.findByLabelText("solve.time_limit_s"), { target: { value: "45" } });
    fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0]);

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ value: 45 });
  });

  it("refuses a number that is not one before sending it", async () => {
    renderPage();

    fireEvent.change(await screen.findByLabelText("solve.time_limit_s"), { target: { value: "soon" } });
    fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0]);

    const message = await screen.findByText(/is a number/);
    expect(message).toHaveAttribute("role", "alert");
  });

  it("shows the values but no way to change them to an account that may not", async () => {
    stub({ me: { username: "planner", display_name: null, capabilities: ["run.submit"] } });
    renderPage();

    expect(await screen.findByLabelText("solve.time_limit_s")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save account" })).toBeInTheDocument();
  });

  it("lets an account change its own password without iam.manage", async () => {
    const sent: { path: string; body: unknown }[] = [];
    stub({
      me: { username: "planner", display_name: "Pat", email: "pat@example.test", capabilities: ["run.submit"] },
      write: (path: string, options?: { body?: string }) => {
        sent.push({ path, body: JSON.parse(options?.body ?? "{}") });
        return Promise.resolve({
          username: "planner",
          display_name: "Pat",
          email: "pat@example.test",
          capabilities: ["run.submit"],
        });
      },
    });
    renderPage();

    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "a new horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Save account" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].path).toBe("/api/v1/me");
    expect(sent[0].body).toMatchObject({ password: "a new horse" });
  });

  it("groups the keys, finds them by words, narrows to those set here, and asks yes or no (UX audit A-3)", async () => {
    const sent: unknown[] = [];
    stub({
      settings: { items: [...SETTINGS.items,
        { key: "retention.audit_days", value: 365, source: "default", value_type: "number", description: "How long audit events are kept" },
        { key: "shadow.enabled", value: false, source: "default", value_type: "boolean", description: "Run a shadow solver alongside" }] },
      write: (_path: string, options?: { body?: string }) => {
        sent.push(JSON.parse(options?.body ?? "{}"));
        return Promise.resolve({ ok: true });
      },
    });
    renderPage();
    expect(await screen.findByRole("region", { name: "Solving and solver choice" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "How long things are kept" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/find a setting/i), { target: { value: "audit" } });
    expect(screen.queryByText("solve.seed")).not.toBeInTheDocument();
    expect(screen.getByText("retention.audit_days")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/find a setting/i), { target: { value: "" } });

    const shadow = screen.getByRole("combobox", { name: "shadow.enabled" });
    expect(shadow).toHaveDisplayValue("inherited: no");
    fireEvent.change(shadow, { target: { value: "true" } });
    expect(shadow).toHaveDisplayValue("Yes");
  });
});

