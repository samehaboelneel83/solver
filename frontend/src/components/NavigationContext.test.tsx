import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DomainRouteProvider, DOMAIN_STORAGE_KEY, useDomain } from "../hooks/useDomain";
import { UnsavedChangesProvider, useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";
import DomainSelector from "./DomainSelector";
import DomainScope from "./DomainScope";
import CommandPalette from "./CommandPalette";
import ContextHeader from "./ContextHeader";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { ApiError, apiFetch } from "../api/client";

function Probe({ dirty = false }: { dirty?: boolean }) {
  const { domainId } = useDomain();
  const location = useLocation();
  useUnsavedChangesGuard(dirty);
  return <><span data-testid="domain">{domainId ?? "none"}</span>
    <span data-testid="location">{location.pathname + location.search}</span></>;
}

function mount(path: string, { dirty = false, palette = false, scope = false } = {}) {
  const onClose = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><DomainRouteProvider><UnsavedChangesProvider>
      <Probe dirty={dirty} /><DomainSelector /><ContextHeader />
      {palette && <CommandPalette open onClose={onClose} can={() => true} />}
      {scope && <Routes><Route path="domains/:domainId" element={<DomainScope />}>
        <Route path="data/records" element={<p>Scoped content</p>} />
      </Route></Routes>}
    </UnsavedChangesProvider></DomainRouteProvider></MemoryRouter>
  </QueryClientProvider>);
  return { onClose };
}

describe("navigation context", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      if (path === "/api/domain/99") throw new ApiError(404, "missing");
      if (path === "/api/domain/7") return { id: 7, name: "Workforce" };
      return { items: [{ id: 7, name: "Workforce" }, { id: 3, name: "Fleet" }], total: 2 };
    });
  });

  it("uses the URL immediately and ignores another tab's domain preference", () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    mount("/domains/7/data/records");
    expect(screen.getByTestId("domain")).toHaveTextContent("7");
    act(() => {
      localStorage.setItem(DOMAIN_STORAGE_KEY, "12");
      window.dispatchEvent(new StorageEvent("storage", { key: DOMAIN_STORAGE_KEY }));
    });
    expect(screen.getByTestId("domain")).toHaveTextContent("7");
  });

  it("does not replace an invalid explicit domain with the stored preference", () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    mount("/domains/invalid/data/records");
    expect(screen.getByTestId("domain")).toHaveTextContent("none");
  });

  it("switches to the new domain's problem list and drops the old child context", async () => {
    mount("/domains/7/problems/9/model?version=20");
    fireEvent.change(await screen.findByRole("combobox", { name: "Workspace" }), { target: { value: "3" } });
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/domains\/3\/problems$/);
    expect(screen.getByTestId("domain")).toHaveTextContent("3");
  });

  it("names the problem alongside the domain in the context header", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => path === "/api/problem/9"
      ? { id: 9, domain_id: 7, name: "Weekly staffing" }
      : { items: [{ id: 7, name: "Workforce" }], total: 1 });
    mount("/domains/7/problems/9/model");
    await waitFor(() => expect(screen.getByTestId("context-header")).toHaveTextContent("Workspace: Workforce / Problem: Weekly staffing"));
  });

  it("keeps the URL and preference when a dirty domain change is cancelled", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mount("/domains/7/problems/9/model", { dirty: true });
    fireEvent.change(await screen.findByRole("combobox", { name: "Workspace" }), { target: { value: "3" } });
    expect(screen.getByTestId("location")).toHaveTextContent("/domains/7/problems/9/model");
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("7");
  });

  it("opens palette destinations in the current URL context", () => {
    mount("/domains/7/problems/9/model?problem=99", { palette: true });
    fireEvent.change(screen.getByRole("combobox", { name: "Go to a page" }), { target: { value: "scenarios" } });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Go to a page" }), { key: "Enter" });
    expect(screen.getByTestId("location")).toHaveTextContent("/domains/7/problems/9/scenarios");
  });

  it("keeps the palette open when leaving an unsaved model is declined", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { onClose } = mount("/domains/7/problems/9/model", { dirty: true, palette: true });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Go to a page" }), { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId("location")).toHaveTextContent("/domains/7/problems/9/model");
  });

  it("does not render domain content before domain validation finishes", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(apiFetch).mockImplementation((path) => path === "/api/domain/7"
      ? new Promise((done) => { resolve = done; }) as ReturnType<typeof apiFetch>
      : Promise.resolve({ items: [], total: 0 }));
    mount("/domains/7/data/records", { scope: true });
    expect(screen.queryByText("Scoped content")).not.toBeInTheDocument();
    await act(async () => resolve({ id: 7, name: "Workforce" }));
    expect(await screen.findByText("Scoped content")).toBeInTheDocument();
  });

  it("blocks unavailable domains without overwriting the remembered domain", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    mount("/domains/99/data/records", { scope: true });
    expect(await screen.findByText("This domain is not available")).toBeInTheDocument();
    expect(screen.queryByText("Scoped content")).not.toBeInTheDocument();
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("3");
  });

  it("blocks content when the API is unreachable and allows retry", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("unreachable"));
    mount("/domains/7/data/records", { scope: true });
    const retry = await screen.findByRole("button", { name: /^Retry/ });
    expect(screen.queryByText("Scoped content")).not.toBeInTheDocument();
    vi.mocked(apiFetch).mockResolvedValue({ id: 7, name: "Workforce" });
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("Scoped content")).toBeInTheDocument());
  });

  it("resolves a domain outside the first page without substituting another domain", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => path === "/api/domain/700"
      ? { id: 700, name: "Large installation" } : { items: [{ id: 3, name: "Fleet" }], total: 700 });
    mount("/domains/700/data/records", { scope: true });
    expect(await screen.findByText("Scoped content")).toBeInTheDocument();
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("700");
  });
});
