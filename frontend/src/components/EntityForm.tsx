import { FormEvent, useState } from "react";
import FkPicker from "./FkPicker";
import type { FieldMeta } from "../types/meta";

type EntityFormProps = {
  fields: FieldMeta[];
  initialValues?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel: string;
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

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Formats a stored value for a date/datetime `<input>`. Date-only values
 * are truncated (no timezone math: a bare calendar date has no instant to
 * convert). Datetime values are read through a `Date` object and rendered
 * back in LOCAL wall-clock time, since that is what a `datetime-local`
 * input expects and displays -- string-slicing an ISO/UTC timestamp would
 * silently show the wrong (UTC) time to the user. */
function toInputValue(field: FieldMeta, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (field.type === "date") {
    return String(value).slice(0, 10);
  }
  if (field.type === "datetime") {
    const date = new Date(String(value));
    if (Number.isNaN(date.getTime())) return String(value);
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(
      date.getHours()
    )}:${pad2(date.getMinutes())}`;
  }
  return String(value);
}

function placeholderFor(field: FieldMeta): string | undefined {
  if (field.default === undefined || field.default === null) return undefined;
  return `default: ${field.default}`;
}

export default function EntityForm({ fields, initialValues, onSubmit, submitLabel }: EntityFormProps) {
  const writableFields = fields.filter((f) => f.writable);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const field of writableFields) {
      initial[field.name] = initialValues?.[field.name] ?? defaultValueFor(field);
    }
    return initial;
  });

  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({});

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {};
    const nextJsonErrors: Record<string, string> = {};
    for (const field of writableFields) {
      const raw = values[field.name];
      if (raw === "") {
        continue; // omit empty optional fields so the backend/DB default applies
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
          nextJsonErrors[field.name] = `${field.name}: invalid JSON`;
        }
      } else if (field.type === "integer" || field.type === "number") {
        payload[field.name] = Number(raw);
      } else {
        payload[field.name] = raw;
      }
    }
    setJsonErrors(nextJsonErrors);
    if (Object.keys(nextJsonErrors).length > 0) {
      return;
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-4">
      {writableFields.map((field) => (
        <div key={field.name}>
          <label className="block text-sm font-medium text-slate-700">
            {field.name}
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
              {jsonErrors[field.name] && (
                <p className="mt-1 text-xs text-red-600">{jsonErrors[field.name]}</p>
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
            </>
          ) : (
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
