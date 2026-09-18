import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EntityForm from "./EntityForm";
import { UnsavedChangesProvider, useConfirmLeave } from "../hooks/useUnsavedChangesGuard";

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

    expect(screen.getByText("expression: invalid JSON", { selector: "p" })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the parsed value once the JSON is fixed", async () => {
    const onSubmit = renderRichForm();

    fireEvent.change(screen.getByTestId("field-expression"), { target: { value: '{"a":' } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByText("expression: invalid JSON", { selector: "p" })).toBeInTheDocument();

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

    expect(screen.getByText("score: expects a number", { selector: "p" })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits a real finite number once corrected", async () => {
    const onSubmit = renderNumericForm();

    fireEvent.change(screen.getByTestId("field-score"), { target: { value: "1e400" } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByText("score: expects a number", { selector: "p" })).toBeInTheDocument();

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

describe("EntityForm accessible labelling (H-3)", () => {
  it("associates a plain field's <label> with its control via htmlFor/id -- findable by getByLabelText", () => {
    renderWithProviders();

    // `{ exact: false }`: "code" is `required`, so its accessible name is
    // "code *" (the visible asterisk, hidden from AT via aria-hidden but
    // still part of the label's rendered text) -- a substring match keeps
    // the assertion independent of that decoration.
    expect(screen.getByLabelText("code", { exact: false })).toBe(screen.getByTestId("field-code"));
  });

  it("associates a checkbox's <label> with the checkbox via htmlFor/id", () => {
    renderWithProviders();

    expect(screen.getByLabelText("is_active", { exact: false })).toBe(screen.getByTestId("field-is_active"));
  });

  it("associates an FK field's <label> with its picker via htmlFor/id -- findable by getByLabelText", () => {
    renderWithProviders();

    expect(screen.getByLabelText("organization_id")).toBe(screen.getByTestId("field-organization_id"));
  });
});

describe("EntityForm one validation path (C-9, C-7, H-5)", () => {
  it("carries noValidate so the browser's own required-field popup never pre-empts the app's validation", () => {
    renderWithProviders();

    expect(document.querySelector("form")).toHaveAttribute("novalidate");
  });

  const combinedValidationFields = [
    { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
    {
      name: "code",
      type: "string" as const,
      required: true,
      writable: true,
      is_fk: false,
      fk_table: null,
      label: "Code",
    },
    { name: "value", type: "json" as const, required: false, writable: true, is_fk: false, fk_table: null },
  ];

  function renderCombinedValidation(onSubmit = vi.fn()) {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm fields={combinedValidationFields} onSubmit={onSubmit} submitLabel="Save" />
      </QueryClientProvider>
    );
    return onSubmit;
  }

  it("an empty required field plus invalid JSON both show in one summary, both get aria-invalid, and nothing is submitted", () => {
    const onSubmit = renderCombinedValidation();

    fireEvent.change(screen.getByTestId("field-value"), { target: { value: '{"a":' } });
    fireEvent.click(screen.getByText("Save"));

    const summary = screen.getByTestId("form-errors");
    expect(summary).toHaveAttribute("role", "alert");
    expect(summary).toHaveTextContent("Code is required.");
    expect(summary).toHaveTextContent("value: invalid JSON");

    expect(screen.getByTestId("field-code")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("field-value")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("moves focus to the error summary after a failed submit", () => {
    renderCombinedValidation();

    fireEvent.click(screen.getByText("Save"));

    expect(screen.getByTestId("form-errors")).toHaveFocus();
  });

  it("does not move focus to the summary from blur-only JSON validation (only a real submit attempt should steal focus)", () => {
    renderRichForm();

    fireEvent.change(screen.getByTestId("field-expression"), { target: { value: "{" } });
    fireEvent.blur(screen.getByTestId("field-expression"));

    // The summary does show the blur-set error (it's driven off the same
    // fieldErrors state as a submit failure), but blur alone must not yank
    // focus away from the field the user is still working in.
    expect(screen.getByTestId("form-errors")).toBeInTheDocument();
    expect(screen.getByTestId("form-errors")).not.toHaveFocus();
  });

  const fkRequiredFields = [
    { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
    {
      name: "organization_id",
      type: "uuid" as const,
      required: true,
      writable: true,
      is_fk: true,
      fk_table: "iam.organization",
      label: "Organization",
    },
  ];

  it("a required FK left empty is validated in-app (not just by the native required attribute) and blocks the request", async () => {
    const onSubmit = vi.fn();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <EntityForm fields={fkRequiredFields} onSubmit={onSubmit} submitLabel="Create" />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByText("Create"));

    expect(screen.getByTestId("form-errors")).toHaveTextContent("Organization is required.");
    expect(onSubmit).not.toHaveBeenCalled();
    // Carried forward from Task 5: the field itself (not just the error
    // summary) must be marked for a screen-reader user navigating field by
    // field -- this requires FkPicker to accept and forward aria-invalid.
    expect(screen.getByTestId("field-organization_id")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("EntityForm JSON blur validation (C-10)", () => {
  it("flags invalid JSON on blur, without waiting for submit", () => {
    const onSubmit = renderRichForm();

    const field = screen.getByTestId("field-expression");
    fireEvent.change(field, { target: { value: "{" } });
    fireEvent.blur(field);

    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("expression: invalid JSON", { selector: "p" })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears the blur-set error once the JSON is fixed and the field is blurred again", () => {
    renderRichForm();

    const field = screen.getByTestId("field-expression");
    fireEvent.change(field, { target: { value: "{" } });
    fireEvent.blur(field);
    expect(field).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(field, { target: { value: "{}" } });
    fireEvent.blur(field);

    expect(field).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("expression: invalid JSON", { selector: "p" })).not.toBeInTheDocument();
  });
});

describe("EntityForm required-field explanation (C-7)", () => {
  it("marks every required field's control with the native required attribute", () => {
    renderWithProviders();

    // is_active (required boolean) is deliberately exempt -- a plain
    // checkbox's `required` means "must be checked", which would wrongly
    // forbid a legitimate `false` value.
    expect(screen.getByTestId("field-code")).toHaveAttribute("required");
  });

  it("explains what the red asterisk means", () => {
    renderWithProviders();

    expect(screen.getByText("Required")).toBeInTheDocument();
  });
});

function LeaveButton() {
  const confirmLeave = useConfirmLeave();
  return (
    <button type="button" onClick={() => confirmLeave()}>
      Leave
    </button>
  );
}

describe("EntityForm unsaved-changes guard (C-3)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prompts window.confirm before an in-app navigation once a field has been edited", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <UnsavedChangesProvider>
          <EntityForm fields={fields} onSubmit={vi.fn()} submitLabel="Create" />
          <LeaveButton />
        </UnsavedChangesProvider>
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Leave"));

    expect(confirmSpy).toHaveBeenCalled();
  });

  it("does not prompt when nothing has been edited yet", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <UnsavedChangesProvider>
          <EntityForm fields={fields} onSubmit={vi.fn()} submitLabel="Create" />
          <LeaveButton />
        </UnsavedChangesProvider>
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByText("Leave"));

    expect(confirmSpy).not.toHaveBeenCalled();
  });
});
