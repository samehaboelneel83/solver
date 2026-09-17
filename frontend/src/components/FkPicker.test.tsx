import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FkPicker from "./FkPicker";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderPicker(value = "", onChange = vi.fn()) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <FkPicker fkTable="iam.organization" value={value} onChange={onChange} testId="field-organization_id" />
    </QueryClientProvider>
  );
  return onChange;
}

describe("FkPicker", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/options?q=nur")) {
        return Promise.resolve([{ id: "org-2", label: "Nur Hospital" }]);
      }
      if (path === "/api/iam/organization/options?ids=org-1") {
        return Promise.resolve([{ id: "org-1", label: "Acme" }]);
      }
      return Promise.resolve([]);
    });
  });

  it("searches by typed query and lists results by label", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });

    await waitFor(
      () => {
        expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining("/options?q=nur"));
      },
      { timeout: 2000 }
    );

    expect(await screen.findByRole("option", { name: "Nur Hospital" })).toBeInTheDocument();
  });

  it("selecting an option calls onChange with the id and shows its label", async () => {
    const onChange = renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });

    const option = await screen.findByRole("option", { name: "Nur Hospital" });
    fireEvent.mouseDown(option);

    expect(onChange).toHaveBeenCalledWith("org-2");
    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Nur Hospital");
    });
  });

  it("resolves an initial value's label via ids=", async () => {
    renderPicker("org-1");

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/api/iam/organization/options?ids=org-1");
    });
    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Acme");
    });
  });

  it("clear button calls onChange with an empty string", async () => {
    const onChange = renderPicker("org-1");

    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Acme");
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("does not query /options?q= before the picker is opened", async () => {
    (apiFetch as any).mockClear();
    renderPicker();

    await screen.findByTestId("field-organization_id");
    expect(apiFetch).not.toHaveBeenCalledWith(expect.stringContaining("/options?q="));
  });

  it("shows a prompt before typing and 'No matches' when a search is empty", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    expect(screen.getByText("Type to search")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(
      () => {
        expect(screen.getByText("No matches")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });
});
