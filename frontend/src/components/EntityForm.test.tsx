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

describe("EntityForm datetime submit round-trip", () => {
  it("converts the local datetime-local string back to an ISO UTC instant on submit (I-1)", async () => {
    const onSubmit = renderRichForm();

    fireEvent.change(screen.getByTestId("field-starts_at"), { target: { value: "2026-03-15T14:45" } });
    fireEvent.click(screen.getByText("Save"));

    const expected = new Date("2026-03-15T14:45").toISOString();
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ starts_at: expected }));
    });
    // Sanity: this is a real UTC instant, not the naive local string passed through.
    expect(expected.endsWith("Z")).toBe(true);
  });
});

describe("EntityForm numeric finite guard", () => {
  // A native `<input type="number">` sanitizes an out-of-range value like "1e400"
  // back to "" on assignment (in jsdom and in real browsers alike -- it can't hold a
  // value that parses to Infinity), so it can never actually deliver "1e400" to
  // onChange; `choices` routes this field through the plain-text/datalist input
  // instead, which lets the test reach the Number.isFinite guard in handleSubmit
  // itself (unreachable via the native widget, but a real contract gap, exactly like
  // attributeValueFromForm's twin guard).
  const numericFields = [
    { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
    {
      name: "score",
      type: "number" as const,
      required: false,
      writable: true,
      is_fk: false,
      fk_table: null,
      choices: ["1", "2", "100"],
    },
  ];

  function renderNumericForm(onSubmit = vi.fn()) {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm fields={numericFields} onSubmit={onSubmit} submitLabel="Save" />
      </QueryClientProvider>
    );
    return onSubmit;
  }

  it("blocks submit with an inline error for a non-finite numeric input (1e400 -> Infinity)", () => {
    const onSubmit = renderNumericForm();

    fireEvent.change(screen.getByTestId("field-score"), { target: { value: "1e400" } });
    fireEvent.click(screen.getByText("Save"));

    expect(screen.getByText("score: expects a number")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits a real finite number once corrected", async () => {
    const onSubmit = renderNumericForm();

    fireEvent.change(screen.getByTestId("field-score"), { target: { value: "1e400" } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByText("score: expects a number")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("field-score"), { target: { value: "42" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ score: 42 });
    });
  });
});

describe("EntityForm clearing fields on edit vs create (M-7)", () => {
  const clearableFields = [
    { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
    { name: "description", type: "string" as const, required: false, writable: true, is_fk: false, fk_table: null },
  ];

  it("sends description: null when an edit form's initially non-empty field is cleared", async () => {
    const onSubmit = vi.fn();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm
          fields={clearableFields}
          initialValues={{ description: "x" }}
          onSubmit={onSubmit}
          submitLabel="Save"
          isEdit
        />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByTestId("field-description"), { target: { value: "" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ description: null });
    });
  });

  it("omits description (does not send null) when a create form's field is left empty", async () => {
    const onSubmit = vi.fn();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm fields={clearableFields} onSubmit={onSubmit} submitLabel="Create" />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({});
    });
  });

  it("omits description on edit when it was already empty and stays empty (nothing to clear)", async () => {
    const onSubmit = vi.fn();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm
          fields={clearableFields}
          initialValues={{ description: "" }}
          onSubmit={onSubmit}
          submitLabel="Save"
          isEdit
        />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({});
    });
  });
});

describe("EntityForm human-readable field labels (B-1)", () => {
  const relationshipFields = [
    { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
    {
      name: "source_entity_id",
      type: "uuid" as const,
      required: true,
      writable: true,
      is_fk: true,
      fk_table: "domain.entity",
      label: "From",
    },
    {
      name: "target_entity_id",
      type: "uuid" as const,
      required: true,
      writable: true,
      is_fk: true,
      fk_table: "domain.entity",
      label: "To",
    },
  ];

  it("renders 'From'/'To' labels instead of the raw source_entity_id/target_entity_id column names", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm fields={relationshipFields} onSubmit={vi.fn()} submitLabel="Create" />
      </QueryClientProvider>
    );

    expect(screen.getByText("From")).toBeInTheDocument();
    expect(screen.getByText("To")).toBeInTheDocument();
    expect(screen.queryByText("source_entity_id")).not.toBeInTheDocument();
    expect(screen.queryByText("target_entity_id")).not.toBeInTheDocument();
  });

  it("falls back to the raw field name when no label is present", () => {
    renderWithProviders();
    expect(screen.getByText("code")).toBeInTheDocument();
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
