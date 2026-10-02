import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSiteBasemap } from "./SiteMap";
import { editorQueryClient } from "../../test/me";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

function Choices() {
  const { options, chosen } = useSiteBasemap("test_basemap");
  return <output data-testid="choices">{`${options.map((o) => o.id).join(",")}|${chosen?.id ?? "none"}`}</output>;
}

function renderWith(items: { key: string; value: unknown }[]) {
  mockFetch.mockImplementation((path: string) =>
    String(path).includes("settings") ? Promise.resolve({ items, total: items.length }) : Promise.resolve({ items: [], total: 0 })
  );
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <Choices />
    </QueryClientProvider>
  );
}

beforeEach(() => mockFetch.mockReset());

describe("useSiteBasemap", () => {
  it("offers the internet imagery by default", async () => {
    renderWith([]);
    await waitFor(() => expect(screen.getByTestId("choices")).toHaveTextContent("builtin-satellite,builtin-streets|builtin-satellite"));
  });

  it("offers none of it when the installation keeps its sites inside", async () => {
    renderWith([{ key: "spatial.internet_basemaps", value: false }]);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("choices")).toHaveTextContent("|none"));
  });
});
