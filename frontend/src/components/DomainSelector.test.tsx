import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DomainSelector from "./DomainSelector";
import { DOMAIN_STORAGE_KEY, useDomain } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

// Listed by name, so the first entry is *not* the lowest id: a fallback that
// picks `min(id)` would choose "beta" (3), and one that picks the stored id's
// neighbour or the last entry would be wrong too. Only "first as listed" is 7.
const DOMAINS = [
  { id: 7, name: "alpha", created_at: "2026-09-19T10:00:00Z" },
  { id: 3, name: "beta", created_at: "2026-09-19T09:00:00Z" },
  { id: 12, name: "gamma", created_at: "2026-09-19T11:00:00Z" },
];

function serveDomains(items: typeof DOMAINS) {
  mockFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/domain/")) return Promise.resolve({ items, total: items.length });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

/** Another consumer of the hook, standing in for a domain-scoped page. */
function ScopeProbe() {
  const { domainId } = useDomain();
  return <span data-testid="scope">{domainId === null ? "none" : String(domainId)}</span>;
}

function renderSelector() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DomainSelector />
      <ScopeProbe />
    </QueryClientProvider>
  );
}

async function selectedDomain(): Promise<HTMLSelectElement> {
  const select = (await screen.findByRole("combobox", { name: "Domain" })) as HTMLSelectElement;
  return select;
}

describe("DomainSelector", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
  });

  it("lists every domain by name, in the order the API returns them", async () => {
    serveDomains(DOMAINS);
    renderSelector();
    const select = await selectedDomain();
    await waitFor(() => expect(select.options).toHaveLength(3));
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("restores the stored domain on mount, even though it isn't the first one", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    serveDomains(DOMAINS);
    renderSelector();
    const select = await selectedDomain();
    await waitFor(() => expect(select.value).toBe("3"));
    expect(screen.getByTestId("scope")).toHaveTextContent("3");
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("3");
  });

  it("falls back to the first listed domain when the stored one no longer exists, and stores that", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "99");
    serveDomains(DOMAINS);
    renderSelector();
    const select = await selectedDomain();
    await waitFor(() => expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("7"));
    expect(select.value).toBe("7");
    // The fallback reaches every consumer, not just the <select>.
    expect(screen.getByTestId("scope")).toHaveTextContent("7");
  });

  it("selects the first listed domain when nothing was stored", async () => {
    serveDomains(DOMAINS);
    renderSelector();
    await waitFor(() => expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("7"));
  });

  it("persists a choice, and a fresh mount (a reload) restores it", async () => {
    serveDomains(DOMAINS);
    const { unmount } = renderSelector();
    const select = await selectedDomain();
    await waitFor(() => expect(select.value).toBe("7"));

    fireEvent.change(select, { target: { value: "12" } });
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("12");
    expect(screen.getByTestId("scope")).toHaveTextContent("12");

    unmount();
    renderSelector();
    const reloaded = await selectedDomain();
    await waitFor(() => expect(reloaded.options).toHaveLength(3));
    expect(reloaded.value).toBe("12");
  });

  it("does not overwrite the stored domain while the list is still loading", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    mockFetch.mockImplementation(() => new Promise(() => {}));
    renderSelector();
    expect(await screen.findByText("Loading domains…")).toBeInTheDocument();
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("3");
  });

  it("does not clear the stored domain when the list fails to load", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    mockFetch.mockRejectedValue(new Error("boom"));
    renderSelector();
    expect(await screen.findByText("Failed to load domains")).toBeInTheDocument();
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("3");
  });

  it("says there are no domains yet, and clears a stale stored id, when the list is empty", async () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "3");
    serveDomains([]);
    renderSelector();
    expect(await screen.findByText("No domains yet")).toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBeNull());
    expect(screen.getByTestId("scope")).toHaveTextContent("none");
  });

  describe("offline (D-7)", () => {
    afterEach(() => onlineManager.setOnline(true));

    it("shows the offline notice instead of an indefinite loading line", async () => {
      onlineManager.setOnline(false);
      mockFetch.mockImplementation(() => new Promise(() => {}));
      renderSelector();
      expect(await screen.findByTestId("offline-notice")).toHaveTextContent(/offline/i);
      expect(screen.queryByText("Loading domains…")).not.toBeInTheDocument();
    });
  });
});
