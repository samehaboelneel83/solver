import { FormEvent, useEffect, useId, useRef, useState } from "react";
import FkPicker from "./FkPicker";
import type { FieldMeta } from "../types/meta";
import { fromDatetimeLocalValue, toDatetimeLocalValue } from "../lib/datetime";
import { fieldLabel } from "../lib/labels";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

export type ServerFieldError = { field: string; message: string };

type EntityFormProps = {
  fields: FieldMeta[];
  initialValues?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel: string;
  /**
   * True when this form is editing an existing record rather than creating
   * a new one. `initialValues` alone can't tell the two apart -- a "New"
   * form can also carry `initialValues` as a prefill from the query string
   * (e.g. `/new?entity_type_id=abc`) -- so callers pass this explicitly.
   * Only an edit form sends an explicit `null` for a nullable field that
   * had a real value and was cleared (M-7); a create form keeps omitting
   * empty fields so column defaults apply.
   */
  isEdit?: boolean;
  /**
   * True while `onSubmit`'s mutation is in flight. Disables the submit
   * button and swaps its label to "Saving…" so a slow request can't be
   * fired twice by a second click (C-4) -- under ~1s latency the button
   * used to stay live with its normal label the whole time.
   */
  isSubmitting?: boolean;
  /**
   * A save that failed with a mapped server-side error (C-5), e.g. a 409
   * naming which field's value collided. Merged into this form's own
   * field-error state so the field gets `aria-invalid`/an inline message
   * and the error summary, same as a client-side validation failure.
   */
  serverError?: ServerFieldError | null;
};

function defaultValueFor(field: FieldMeta): unknown {
  if (field.type === "boolean") {
    // Non-required booleans start as "" ("(use default)"), which
    // handleSubmit omits so the column's own default applies. Always
    // sending `false` here would silently invert defaults that are `true`
    // (e.g. is_active).
    return field.required ? false : "";
  }
  return "";
}

/** Formats a stored value for a date/datetime `<input>`. Date-only values
 * are truncated (no timezone math: a bare calendar date has no instant to
 * convert). Datetime values go through the shared local-time helper, since
 * that is what a `datetime-local` input expects and displays -- string-
 * slicing an ISO/UTC timestamp would silently show the wrong (UTC) time to
 * the user. */
function toInputValue(field: FieldMeta, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (field.type === "date") {
    return String(value).slice(0, 10);
  }
  if (field.type === "datetime") {
    return toDatetimeLocalValue(String(value));
  }
  return String(value);
}

function placeholderFor(field: FieldMeta): string | undefined {
  if (field.default === undefined || field.default === null) return undefined;
  return `default: ${field.default}`;
}

function hasNonEmptyValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

export default function EntityForm({
  fields,
  initialValues,
  onSubmit,
  submitLabel,
  isEdit = false,
  isSubmitting = false,
  serverError = null,
}: EntityFormProps) {
  const writableFields = fields.filter((f) => f.writable);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const field of writableFields) {
      initial[field.name] = initialValues?.[field.name] ?? defaultValueFor(field);
    }
    return initial;
  });

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [isDirty, setIsDirty] = useState(false);

  // C-3: warn before an edit is discarded, either by an in-app nav click
  // (via the shared confirmLeave() guard AppShell/Cancel links consult) or
  // by closing the tab (beforeunload). See the hook's own doc comment for
  // why the browser's Back button isn't covered.
  useUnsavedChangesGuard(isDirty);

  // useId() once per form, then derive a stable per-field id from it --
  // calling useId() itself inside the fields.map() below would violate the
  // rules of hooks (a hook call inside a loop/callback).
  const formId = useId();
  const fieldId = (name: string) => `${formId}-field-${name}`;
  const errorId = (name: string) => `${formId}-field-${name}-error`;

  // Moves focus to the error summary after a failed submit attempt (H-5) --
  // but NOT after a blur-triggered JSON error, which shouldn't yank focus
  // away from the field the user is still working in. Set to true right
  // before a submit-triggered setFieldErrors call; consumed (and reset) by
  // the effect below on the next render.
  const pendingFocusRef = useRef(false);
  const errorSummaryRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (pendingFocusRef.current) {
      pendingFocusRef.current = false;
      errorSummaryRef.current?.focus();
    }
  }, [fieldErrors]);

  // A mapped server-side error (C-5, e.g. a 409 naming a field) merges into
  // the same field-error state a client-side validation failure would use,
  // so the field gets aria-invalid/an inline message and the summary too.
  useEffect(() => {
    if (serverError) {
      pendingFocusRef.current = true;
      setFieldErrors((prev) => ({ ...prev, [serverError.field]: serverError.message }));
    }
  }, [serverError]);

  function setField(name: string, value: unknown) {
    setIsDirty(true);
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  // C-10: flags invalid JSON as soon as the field is left, instead of only
  // on submit. Empty is left alone (an empty optional JSON field is valid;
  // required-ness is checked separately in handleSubmit).
  function handleJsonBlur(field: FieldMeta) {
    const raw = values[field.name];
    if (typeof raw !== "string" || raw === "") {
      clearFieldError(field.name);
      return;
    }
    try {
      JSON.parse(raw);
      clearFieldError(field.name);
    } catch {
      setFieldErrors((prev) => ({ ...prev, [field.name]: `${field.name}: invalid JSON` }));
    }
  }

  function clearFieldError(name: string) {
    setFieldErrors((prev) => {
      if (!(name in prev)) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {};
    const nextFieldErrors: Record<string, string> = {};
    for (const field of writableFields) {
      const raw = values[field.name];

      // C-9/C-7: this is the ONE place required-ness is enforced. The form
      // carries `noValidate` so the browser's own required-field check
      // (which used to only exist on the two FK pickers, and always fired
      // before this validate() could run) never fires; every required
      // field -- not just FK pickers -- is checked here instead. Booleans
      // are exempt: `defaultValueFor` always gives a required boolean a
      // concrete true/false, so it's never "empty".
      if (field.required && field.type !== "boolean" && (raw === "" || raw === null || raw === undefined)) {
        nextFieldErrors[field.name] = `${fieldLabel(field)} is required.`;
        continue;
      }

      if (raw === "") {
        // On EDIT, a nullable field that started with a real value and was
        // cleared sends an explicit `null` so the column actually gets
        // cleared (matching the Graph Editor's PropertyPanel) -- omitting
        // it here would just leave the old value in place. On CREATE,
        // empties stay omitted so column defaults apply. Booleans are the
        // one exception in both modes: their tri-state "(use default)"
        // always means "leave the column alone", never "clear it".
        if (field.type !== "boolean" && isEdit && !field.required && hasNonEmptyValue(initialValues?.[field.name])) {
          payload[field.name] = null;
        }
        continue;
      }
      if (field.type === "boolean" && typeof raw === "string") {
        // Tri-state select value; a required boolean's checkbox already
        // yields a real boolean and falls through to the else branch.
        payload[field.name] = raw === "true";
      } else if (field.type === "json" && typeof raw === "string") {
        try {
          payload[field.name] = JSON.parse(raw);
        } catch {
          // Storing invalid JSON as a plain string used to silently corrupt
          // the column; block the submit and point at the offending field
          // instead.
          nextFieldErrors[field.name] = `${field.name}: invalid JSON`;
        }
      } else if (field.type === "integer" || field.type === "number") {
        const num = Number(raw);
        if (!Number.isFinite(num)) {
          // "abc" -> NaN, "1e400" -> Infinity: both are non-finite and
          // JSON.stringify silently turns either into `null`, which would
          // look identical to the user explicitly clearing the field --
          // block the submit instead of quietly deleting data.
          nextFieldErrors[field.name] = `${field.name}: expects a number`;
        } else {
          payload[field.name] = num;
        }
      } else if (field.type === "datetime" && typeof raw === "string") {
        // The input holds a naive local wall-clock string; convert it to a
        // real UTC instant before sending, or every save would drift by the
        // browser's timezone offset.
        payload[field.name] = fromDatetimeLocalValue(raw);
      } else {
        payload[field.name] = raw;
      }
    }
    pendingFocusRef.current = Object.keys(nextFieldErrors).length > 0;
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) {
      return;
    }
    onSubmit(payload);
  }

  function renderControl(field: FieldMeta, id: string, hasError: boolean) {
    const describedBy = hasError ? errorId(field.name) : undefined;
    const ariaInvalid = hasError ? ("true" as const) : undefined;

    if (field.type === "boolean") {
      if (field.required) {
        return (
          <input
            id={id}
            type="checkbox"
            checked={Boolean(values[field.name])}
            onChange={(e) => setField(field.name, e.target.checked)}
            data-testid={`field-${field.name}`}
          />
        );
      }
      return (
        <select
          id={id}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={String(values[field.name] ?? "")}
          onChange={(e) => setField(field.name, e.target.value)}
          data-testid={`field-${field.name}`}
        >
          <option value="">(use default)</option>
          <option value="true">True</option>
          <option value="false">False</option>
        </select>
      );
    }

    if (field.type === "json") {
      return (
        <textarea
          id={id}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
          rows={4}
          placeholder={placeholderFor(field)}
          required={field.required}
          aria-invalid={ariaInvalid}
          aria-describedby={describedBy}
          value={
            typeof values[field.name] === "string"
              ? (values[field.name] as string)
              : JSON.stringify(values[field.name] ?? "")
          }
          onChange={(e) => setField(field.name, e.target.value)}
          onBlur={() => handleJsonBlur(field)}
          data-testid={`field-${field.name}`}
        />
      );
    }

    if (field.choices && field.choices.length > 0) {
      return (
        <>
          <input
            id={id}
            type="text"
            list={`choices-${field.name}`}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder={placeholderFor(field)}
            required={field.required}
            aria-invalid={ariaInvalid}
            aria-describedby={describedBy}
            value={String(values[field.name] ?? "")}
            onChange={(e) => setField(field.name, e.target.value)}
            data-testid={`field-${field.name}`}
          />
          <datalist id={`choices-${field.name}`}>
            {field.choices.map((choice) => (
              <option key={choice} value={choice} />
            ))}
          </datalist>
        </>
      );
    }

    return (
      <input
        id={id}
        type={
          field.type === "integer" || field.type === "number"
            ? "number"
            : field.type === "date"
              ? "date"
              : field.type === "datetime"
                ? "datetime-local"
                : "text"
        }
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        placeholder={placeholderFor(field)}
        required={field.required}
        aria-invalid={ariaInvalid}
        aria-describedby={describedBy}
        value={toInputValue(field, values[field.name])}
        onChange={(e) => setField(field.name, e.target.value)}
        data-testid={`field-${field.name}`}
      />
    );
  }

  const hasErrors = Object.keys(fieldErrors).length > 0;
  const hasRequiredField = writableFields.some((f) => f.required);

  return (
    <form onSubmit={handleSubmit} noValidate className="max-w-xl space-y-4">
      {hasErrors && (
        <div
          ref={errorSummaryRef}
          data-testid="form-errors"
          role="alert"
          tabIndex={-1}
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          <p className="font-medium">Please fix the following before submitting:</p>
          <ul className="list-disc pl-5">
            {writableFields
              .filter((field) => fieldErrors[field.name])
              .map((field) => (
                <li key={field.name}>{fieldErrors[field.name]}</li>
              ))}
          </ul>
        </div>
      )}
      {hasRequiredField && (
        <p className="text-xs text-slate-500">
          <span className="text-red-500" aria-hidden="true">
            *
          </span>{" "}
          Required
        </p>
      )}
      {writableFields.map((field) => {
        const id = fieldId(field.name);
        const hasError = Boolean(fieldErrors[field.name]);
        const isFk = field.is_fk && field.fk_table;
        return (
          <div key={field.name}>
            {isFk ? (
              // FkPicker doesn't accept an `id`/aria-* passthrough (its
              // internals are Task 6's to change), so this field is
              // labelled by wrapping it in the <label> instead of
              // htmlFor/id -- an equally valid accessible-name mechanism
              // (WCAG 4.1.2 / axe's `label` rule accept either).
              <label className="block text-sm font-medium text-slate-700">
                {fieldLabel(field)}
                {field.required && (
                  <span className="text-red-500" aria-hidden="true">
                    {" "}
                    *
                  </span>
                )}
                <FkPicker
                  fkTable={field.fk_table as string}
                  value={String(values[field.name] ?? "")}
                  onChange={(v) => setField(field.name, v)}
                  required={field.required}
                  testId={`field-${field.name}`}
                />
              </label>
            ) : (
              <>
                <label htmlFor={id} className="block text-sm font-medium text-slate-700">
                  {fieldLabel(field)}
                  {field.required && (
                    <span className="text-red-500" aria-hidden="true">
                      {" "}
                      *
                    </span>
                  )}
                </label>
                {renderControl(field, id, hasError)}
              </>
            )}
            {hasError && (
              <p id={errorId(field.name)} className="mt-1 text-xs text-red-600">
                {fieldErrors[field.name]}
              </p>
            )}
          </div>
        );
      })}
      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
