import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BulkPanel from "./BulkPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

describe("BulkPanel (queue R21)", () => {
  it("sends the chosen file with its options and lists each fault by row and column", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: false, rows: 3, written: 0, skipped: 3, dry_run: false,
      faults: [{ row: 3, column: "capacity", message: "must be a whole number, not 'ten'" }],
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BulkPanel base="/api/v1/entity-types/3" what="site entities" />
      </QueryClientProvider>
    );
    const file = new File(["key,capacity\nnorth,ten\n"], "sites.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("File to upload"), { target: { files: [file] } });
    fireEvent.click(screen.getByLabelText(/Write the clean rows/));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(screen.getByText("must be a whole number, not 'ten'")).toBeInTheDocument());
    const [path, init] = vi.mocked(apiFetch).mock.calls[0];
    expect(path).toBe("/api/v1/entity-types/3/upload?clean_only=true&dry_run=false");
    expect((init?.body as FormData).get("file")).toBe(file);
    expect(screen.getByText(/Nothing was written: 1 fault/)).toBeInTheDocument();
  });
});
