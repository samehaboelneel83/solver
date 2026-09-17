import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityForm from "./EntityForm";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
  { name: "is_active", type: "boolean" as const, required: true, writable: true, is_fk: false, fk_table: null },
  {
    name: "organization_id",
    type: "uuid" as const,
    required: false,
    writable: true,
    is_fk: true,
    fk_table: "iam.organization",
  },
];

function renderWithProviders(onSubmit = vi.fn()) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <EntityForm fields={fields} onSubmit={onSubmit} submitLabel="Create" />
    </QueryClientProvider>
  );
  return onSubmit;
}

describe("EntityForm", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue({ items: [{ id: "org-1", code: "acme" }], total: 1 });
  });

  it("does not render non-writable fields", () => {
    renderWithProviders();
    expect(screen.queryByTestId("field-id")).not.toBeInTheDocument();
  });

  it("renders a checkbox for boolean fields and a searchable picker for FK fields", () => {
    renderWithProviders();
    expect(screen.getByTestId("field-is_active")).toHaveAttribute("type", "checkbox");
    expect(screen.getByTestId("field-organization_id")).toHaveAttribute("role", "combobox");
  });

  it("submits typed values and omits empty optional fields", async () => {
    const onSubmit = renderWithProviders();

    fireEvent.change(screen.getByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByTestId("field-is_active"));
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ code: "employee", is_active: true });
    });
  });
});

// A NOT NULL column with a client-side ORM default (e.g. is_active) now
// arrives as required:false. A plain checkbox would always send a concrete
// true/false and default to false, silently inverting defaults that are
// actually true -- so these render as a tri-state select instead.
const optionalBooleanFields = [
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
  {
    name: "is_active",
    type: "boolean" as const,
    required: false,
    writable: true,
    is_fk: false,
    fk_table: null,
  },
];

function renderOptionalBoolean(onSubmit = vi.fn()) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <EntityForm fields={optionalBooleanFields} onSubmit={onSubmit} submitLabel="Create" />
    </QueryClientProvider>
  );
  return onSubmit;
}

describe("EntityForm optional booleans", () => {
  it("renders a tri-state select with a (use default) option, not a checkbox", () => {
    renderOptionalBoolean();

    const control = screen.getByTestId("field-is_active");
    expect(control.tagName).toBe("SELECT");
    expect(control).not.toHaveAttribute("type", "checkbox");
    expect(screen.getByText("(use default)")).toBeInTheDocument();
    expect((control as HTMLSelectElement).value).toBe("");
  });

  it("omits an untouched optional boolean so the column default applies", async () => {
    const onSubmit = renderOptionalBoolean();

    fireEvent.change(screen.getByTestId("field-code"), { target: { value: "acme" } });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ code: "acme" });
    });
  });

  it("sends a real boolean when the optional boolean is explicitly chosen", async () => {
    const onSubmit = renderOptionalBoolean();

    fireEvent.change(screen.getByTestId("field-code"), { target: { value: "acme" } });
    fireEvent.change(screen.getByTestId("field-is_active"), { target: { value: "false" } });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ code: "acme", is_active: false });
    });
  });
});

const richFields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "expression", type: "json" as const, required: false, writable: true, is_fk: false, fk_table: null },
  { name: "starts_at", type: "datetime" as const, required: false, writable: true, is_fk: false, fk_table: null },
  {
    name: "status",
    type: "string" as const,
    required: false,
    writable: true,
    is_fk: false,
    fk_table: null,
    choices: ["DRAFT", "ACTIVE"],
  },
  {
    name: "priority",
    type: "string" as const,
    required: false,
    writable: true,
    is_fk: false,
    fk_table: null,
    default: "DRAFT",
  },
];

function renderRichForm(onSubmit = vi.fn(), initialValues?: Record<string, unknown>) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <EntityForm fields={richFields} initialValues={initialValues} onSubmit={onSubmit} submitLabel="Save" />
    </QueryClientProvider>
  );
  return onSubmit;
}

describe("EntityForm JSON validation", () => {
  it("blocks submit and shows an inline error for invalid JSON", () => {
    const onSubmit = renderRichForm();

    fireEvent.change(screen.getByTestId("field-expression"), { target: { value: '{"a":' } });
    fireEvent.click(screen.getByText("Save"));

    expect(screen.getByText("expression: invalid JSON")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the parsed value once the JSON is fixed", async () => {
    const onSubmit = renderRichForm();

    fireEvent.change(screen.getByTestId("field-expression"), { target: { value: '{"a":' } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByText("expression: invalid JSON")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("field-expression"), { target: { value: '{"a": 1}' } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ expression: { a: 1 } });
    });
    expect(screen.queryByText("expression: invalid JSON")).not.toBeInTheDocument();
  });
});

describe("EntityForm date/datetime formatting", () => {
  it("renders a datetime initial value as a local-time datetime-local string", () => {
    const isoValue = "2026-10-01T08:00:00Z";
    const expected = (() => {
      const date = new Date(isoValue);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
        date.getHours()
      )}:${pad(date.getMinutes())}`;
    })();

    renderRichForm(vi.fn(), { starts_at: isoValue });

    expect((screen.getByTestId("field-starts_at") as HTMLInputElement).value).toBe(expected);
  });
});

describe("EntityForm hints", () => {
  it("renders a datalist of choices for a field with choices", () => {
    renderRichForm();

    const input = screen.getByTestId("field-status");
    expect(input).toHaveAttribute("list", "choices-status");
    const datalist = document.getElementById("choices-status");
    const optionValues = Array.from(datalist?.querySelectorAll("option") ?? []).map((o) => o.getAttribute("value"));
    expect(optionValues).toEqual(["DRAFT", "ACTIVE"]);
  });

  it("shows the column default as a placeholder", () => {
    renderRichForm();

    expect(screen.getByTestId("field-priority")).toHaveAttribute("placeholder", "default: DRAFT");
  });
});
