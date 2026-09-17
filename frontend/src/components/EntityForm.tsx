import { FormEvent, useState } from "react";
import FkPicker from "./FkPicker";
import type { FieldMeta } from "../types/meta";
import { fromDatetimeLocalValue, toDatetimeLocalValue } from "../lib/datetime";
import { fieldLabel } from "../lib/labels";

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

export default function EntityForm({ fields, initialValues, onSubmit, submitLabel, isEdit = false }: EntityFormProps) {
  const writableFields = fields.filter((f) => f.writable);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const field of writableFields) {
      initial[field.name] = initialValues?.[field.name] ?? defaultValueFor(field);
    }
    return initial;
  });

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {};
    const nextFieldErrors: Record<string, string> = {};
    for (const field of writableFields) {
      const raw = values[field.name];
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
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) {
      return;
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-4">
      {writableFields.map((field) => (
        <div key={field.name}>
          <label className="block text-sm font-medium text-slate-700">
            {fieldLabel(field)}
            {field.required && <span className="text-red-500"> *</span>}
          </label>
          {field.is_fk && field.fk_table ? (
            <FkPicker
              fkTable={field.fk_table}
              value={String(values[field.name] ?? "")}
              onChange={(v) => setField(field.name, v)}
              required={field.required}
              testId={`field-${field.name}`}
            />
          ) : field.type === "boolean" ? (
            field.required ? (
              <input
                type="checkbox"
                checked={Boolean(values[field.name])}
                onChange={(e) => setField(field.name, e.target.checked)}
                data-testid={`field-${field.name}`}
              />
            ) : (
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                value={String(values[field.name] ?? "")}
                onChange={(e) => setField(field.name, e.target.value)}
                data-testid={`field-${field.name}`}
              >
                <option value="">(use default)</option>
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            )
          ) : field.type === "json" ? (
            <>
              <textarea
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
                rows={4}
                placeholder={placeholderFor(field)}
                value={
                  typeof values[field.name] === "string"
                    ? (values[field.name] as string)
                    : JSON.stringify(values[field.name] ?? "")
                }
                onChange={(e) => setField(field.name, e.target.value)}
                data-testid={`field-${field.name}`}
              />
              {fieldErrors[field.name] && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors[field.name]}</p>
              )}
            </>
          ) : field.choices && field.choices.length > 0 ? (
            <>
              <input
                type="text"
                list={`choices-${field.name}`}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                placeholder={placeholderFor(field)}
                value={String(values[field.name] ?? "")}
                onChange={(e) => setField(field.name, e.target.value)}
                data-testid={`field-${field.name}`}
              />
              <datalist id={`choices-${field.name}`}>
                {field.choices.map((choice) => (
                  <option key={choice} value={choice} />
                ))}
              </datalist>
              {fieldErrors[field.name] && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors[field.name]}</p>
              )}
            </>
          ) : (
            <>
              <input
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
                value={toInputValue(field, values[field.name])}
                onChange={(e) => setField(field.name, e.target.value)}
                data-testid={`field-${field.name}`}
              />
              {fieldErrors[field.name] && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors[field.name]}</p>
              )}
            </>
          )}
        </div>
      ))}
      <button
        type="submit"
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        {submitLabel}
      </button>
    </form>
  );
}
