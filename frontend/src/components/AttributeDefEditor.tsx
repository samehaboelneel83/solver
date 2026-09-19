import { FormEvent, ReactNode, useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { validationErrors, type AttrType, type AttributeDef, type AttributeDefCreate, type EntityRole } from "../api/v1";

/*
 * The attribute-definition form, plus the small pieces of form plumbing the
 * two entity-type pages share with it. The conventions are EntityForm's: a
 * visible <label> per control with a red, aria-hidden asterisk for required
 * fields; an inline `text-xs text-red-600` message that the control points
 * at with `aria-describedby`; `aria-invalid` on the control; and an error
 * summary (`role="alert"`, focused after a failed submit) listing every
 * message. EntityForm itself is metadata-driven (`FieldMeta` from
 * /api/meta), which these v1 tables are not, so the conventions are
 * reused rather than the component.
 */

// --- literals ---------------------------------------------------------------
//
// The same labels as `backend/app/api/entity_types.py` (`EntityRole`,
// `AttrType`), which in turn mirror the DDL's two enum types. Kept in the
// server's order.

export const ENTITY_ROLES: { value: EntityRole; label: string }[] = [
  { value: "agent", label: "Agent" },
  { value: "resource", label: "Resource" },
  { value: "time", label: "Time" },
  { value: "location", label: "Location" },
  { value: "task", label: "Task" },
  { value: "org", label: "Organization" },
  { value: "other", label: "Other" },
];

export const DATA_TYPES: { value: AttrType; label: string }[] = [
  { value: "integer", label: "Integer" },
  { value: "number", label: "Number" },
  { value: "text", label: "Text" },
  { value: "boolean", label: "Yes / no" },
  { value: "enum", label: "Choice from a list" },
  { value: "time", label: "Time of day" },
  { value: "date", label: "Date" },
];

export function roleLabel(role: string): string {
  return ENTITY_ROLES.find((r) => r.value === role)?.label ?? role;
}

export function dataTypeLabel(type: string): string {
  return DATA_TYPES.find((t) => t.value === type)?.label ?? type;
}

// --- names ------------------------------------------------------------------

// The server's `^[a-z][a-z0-9_]*$` as a full match. JavaScript's `$`
// without the `m` flag matches only at the very end of the input, so a
// trailing newline cannot slip through the way it can with Python's `re`.
const NAME_RE = /^[a-z][a-z0-9_]*$/;
const NAME_RULE =
  "Use a lowercase letter first, then lowercase letters, digits or underscores (the name is used as-is in model expressions).";

/** Why `name` would be refused, or null. `isAttribute` adds the one extra
 * rule `attribute_def` has: `id` is reserved. */
export function nameProblem(name: string, isAttribute: boolean): string | null {
  if (name === "") return "Name is required.";
  if (!NAME_RE.test(name)) return `Name: ${NAME_RULE}`;
  if (isAttribute && name === "id") return "Name: \"id\" is reserved, because every entity already has an id.";
  return null;
}

// --- typed defaults -----------------------------------------------------------

export type ParsedDefault = { ok: true; value: unknown } | { ok: false; message: string };

const INTEGER_RE = /^[+-]?\d+$/;
const NUMBER_RE = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/;

/**
 * Turns what the user typed into the JSON value `default_value` stores, or
 * says why it can't. This is the only guard there is: the server stores
 * `default_value` without checking it against `data_type` (Task 5's
 * deferred item), and the entity trigger then materialises it into every
 * new entity -- so a wrong default saved here makes every later entity
 * write of this type fail. Empty always means "no default" (SQL NULL,
 * Ruling 18).
 *
 * The rules are the entity trigger's (`entity_validate`, migration 0006)
 * made stricter where the trigger is loose: `integer` takes digits only
 * (the trigger would also take `5.0`), and `date`/`time` must be a real
 * ISO date / HH:MM time (the trigger takes any string).
 */
export function parseDefaultValue(type: AttrType, raw: string, enumValues: string[]): ParsedDefault {
  if (raw === "") return { ok: true, value: null };
  const text = raw.trim();
  switch (type) {
    case "integer": {
      if (!INTEGER_RE.test(text)) {
        return { ok: false, message: "Default value: must be a whole number, such as 8 or -2 (no decimals)." };
      }
      const value = Number(text);
      if (!Number.isSafeInteger(value)) {
        return { ok: false, message: "Default value: this whole number is too large to store exactly." };
      }
      return { ok: true, value };
    }
    case "number": {
      const value = Number(text);
      if (!NUMBER_RE.test(text) || !Number.isFinite(value)) {
        return { ok: false, message: "Default value: must be a number, such as 2.5." };
      }
      return { ok: true, value };
    }
    case "boolean":
      if (raw === "true") return { ok: true, value: true };
      if (raw === "false") return { ok: true, value: false };
      return { ok: false, message: "Default value: must be True or False." };
    case "enum":
      if (!enumValues.includes(raw)) {
        return { ok: false, message: `Default value: "${raw}" is not one of the allowed values.` };
      }
      return { ok: true, value: raw };
    case "date": {
      const match = DATE_RE.exec(text);
      if (match) {
        const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
        const date = new Date(Date.UTC(year, month - 1, day));
        if (date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day) {
          return { ok: true, value: text };
        }
      }
      return { ok: false, message: "Default value: must be a date (YYYY-MM-DD)." };
    }
    case "time":
      if (!TIME_RE.test(text)) return { ok: false, message: "Default value: must be a time of day (HH:MM)." };
      return { ok: true, value: text };
    case "text":
    default:
      return { ok: true, value: raw };
  }
}

/** A stored default as the text its input holds. A value of the wrong JSON
 * type (one saved before this editor, or through the API) is shown as-is
 * rather than hidden, so the user can see it and replace it. */
function draftFromValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** A stored default for display in the attributes table. */
export function formatDefault(value: unknown): string {
  if (value === null || value === undefined) return "No default";
  if (value === true) return "True";
  if (value === false) return "False";
  return draftFromValue(value);
}

function parseEnumValues(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

// --- server errors ------------------------------------------------------------

export type FieldErrors = Record<string, string>;

/**
 * Splits a failed save into messages for the fields on screen and a
 * general message for everything else.
 *
 * - A list-shaped 422 (Pydantic, or the router's own `field_error`) names
 *   its field in `loc[1]`; entries for a field in `fields` go to that
 *   field, the rest become the general message.
 * - A 409 whose string `detail` says "already exists" is the only unique
 *   constraint either table has -- `(domain_id, name)` or
 *   `(entity_type_id, name)` -- so it goes to `name`, reworded: the raw
 *   text names the constraint ("...the same entity_type_id_name...").
 * - Anything else is `formatApiError`'s text.
 */
export function serverFieldErrors(
  err: unknown,
  fields: string[],
  noun: "attribute" | "entity type"
): { fields: FieldErrors; general: string | null } {
  const items = validationErrors(err);
  if (items.length > 0) {
    const mapped: FieldErrors = {};
    const rest: string[] = [];
    for (const item of items) {
      const field = item.loc?.[1];
      if (typeof field === "string" && fields.includes(field) && !(field in mapped)) {
        mapped[field] = item.msg;
      } else {
        rest.push(item.msg);
      }
    }
    return { fields: mapped, general: rest.length > 0 ? rest.join("\n") : null };
  }
  const message = formatApiError(err);
  if (err instanceof ApiError && err.status === 409 && /already exists/.test(message) && fields.includes("name")) {
    const text =
      noun === "attribute"
        ? "Name: this entity type already has an attribute with this name."
        : "Name: this domain already has an entity type with this name.";
    return { fields: { name: text }, general: null };
  }
  return { fields: {}, general: message };
}

// --- shared form plumbing ---------------------------------------------------------

export const INPUT_CLASS =
  "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 aria-[invalid=true]:border-red-500";

export function FieldLabel({ htmlFor, required, children }: { htmlFor: string; required?: boolean; children: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">
      {children}
      {required && (
        <span className="text-red-500" aria-hidden="true">
          {" "}
          *
        </span>
      )}
    </label>
  );
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 text-xs text-red-600">
      {message}
    </p>
  );
}

/** EntityForm's error summary: listed in field order, focused after a failed submit. */
export function ErrorSummary({
  errors,
  order,
  summaryRef,
}: {
  errors: FieldErrors;
  order: string[];
  summaryRef: React.RefObject<HTMLDivElement>;
}) {
  const names = order.filter((name) => errors[name]);
  if (names.length === 0) return null;
  return (
    <div
      ref={summaryRef}
      role="alert"
      tabIndex={-1}
      data-testid="form-errors"
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      <p className="font-medium">Please fix the following before submitting:</p>
      <ul className="list-disc pl-5">
        {names.map((name) => (
          <li key={name}>{errors[name]}</li>
        ))}
      </ul>
    </div>
  );
}

/** `aria-describedby` from whichever ids apply, or undefined. */
export function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  const present = ids.filter(Boolean);
  return present.length > 0 ? present.join(" ") : undefined;
}

/** Field errors whose summary takes focus on the render after a failed submit. */
export function useFieldErrors(serverErrors: FieldErrors | null | undefined) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const summaryRef = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef(false);

  useEffect(() => {
    if (pendingFocus.current) {
      pendingFocus.current = false;
      summaryRef.current?.focus();
    }
  }, [errors]);

  // A server-side refusal merges into the same state a client-side one
  // uses, so the field is marked the same way either way.
  useEffect(() => {
    if (serverErrors && Object.keys(serverErrors).length > 0) {
      pendingFocus.current = true;
      setErrors((prev) => ({ ...prev, ...serverErrors }));
    }
  }, [serverErrors]);

  function replace(next: FieldErrors) {
    pendingFocus.current = Object.keys(next).length > 0;
    setErrors(next);
  }

  return { errors, replace, summaryRef };
}

// --- the editor -------------------------------------------------------------------

const FIELD_ORDER = ["name", "data_type", "required", "unit", "enum_values", "default_value"];
export const ATTRIBUTE_FIELDS = FIELD_ORDER;

const MATERIALISED_NOTE =
  "Existing entities keep the default they were given. A default is written into each entity when the entity is saved, so changing it here only affects entities saved from now on.";

type AttributeDefEditorProps = {
  /** The attribute being edited; absent when adding a new one. */
  initial?: AttributeDef | null;
  onSubmit: (body: AttributeDefCreate) => void;
  onCancel?: () => void;
  submitLabel: string;
  /** The form's accessible name, e.g. "New attribute". */
  formLabel?: string;
  isSubmitting?: boolean;
  /** Messages from a refused save, keyed by field (see `serverFieldErrors`). */
  serverErrors?: FieldErrors | null;
  /** Move focus to the name field on mount (when opened by the user). */
  autoFocus?: boolean;
};

export default function AttributeDefEditor({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
  formLabel,
  isSubmitting = false,
  serverErrors,
  autoFocus = false,
}: AttributeDefEditorProps) {
  const isEdit = Boolean(initial);
  const [name, setName] = useState(initial?.name ?? "");
  const [dataType, setDataType] = useState<AttrType>(initial?.data_type ?? "text");
  const [required, setRequired] = useState(initial?.required ?? false);
  const [unit, setUnit] = useState(initial?.unit ?? "");
  const [enumText, setEnumText] = useState((initial?.enum_values ?? []).join("\n"));
  const [defaultDraft, setDefaultDraft] = useState(draftFromValue(initial?.default_value));
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);

  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) nameRef.current?.focus();
  }, [autoFocus]);

  const enumValues = parseEnumValues(enumText);

  function clearError(field: string) {
    if (errors[field]) {
      const next = { ...errors };
      delete next[field];
      replace(next);
    }
  }

  function changeType(next: AttrType) {
    setDataType(next);
    // A default typed for one data type means nothing under another --
    // "5" as text is not 5 as an integer, and "night" is not a date.
    // Starting over is the only reading that cannot store a wrong value.
    setDefaultDraft("");
    const nextErrors = { ...errors };
    delete nextErrors.default_value;
    delete nextErrors.enum_values;
    delete nextErrors.data_type;
    replace(nextErrors);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: FieldErrors = {};

    const nameError = nameProblem(name, true);
    if (nameError) next.name = nameError;

    if (dataType === "enum") {
      if (enumValues.length === 0) {
        next.enum_values = "Allowed values: list at least one, one per line.";
      } else {
        const seen = new Set<string>();
        const dupes = enumValues.filter((v) => (seen.has(v) ? true : (seen.add(v), false)));
        if (dupes.length > 0) next.enum_values = `Allowed values: "${dupes[0]}" is listed more than once.`;
      }
    }

    const parsed = parseDefaultValue(dataType, defaultDraft, enumValues);
    if (!parsed.ok) next.default_value = parsed.message;

    replace(next);
    if (Object.keys(next).length > 0 || !parsed.ok) return;

    const trimmedUnit = unit.trim();
    onSubmit({
      name,
      data_type: dataType,
      required,
      unit: trimmedUnit === "" ? null : trimmedUnit,
      enum_values: dataType === "enum" ? enumValues : null,
      default_value: parsed.value,
    });
  }

  function renderDefaultControl() {
    const invalid = errors.default_value ? ("true" as const) : undefined;
    const common = {
      id: id("default_value"),
      "aria-invalid": invalid,
      "aria-describedby": describedBy(
        defaultHint[dataType] && id("default_value-hint"),
        id("default_value-note"),
        errors.default_value && errorId("default_value")
      ),
      className: INPUT_CLASS,
    };

    if (dataType === "boolean" || dataType === "enum") {
      const options = dataType === "boolean" ? ["true", "false"] : enumValues;
      const stale = defaultDraft !== "" && !options.includes(defaultDraft);
      return (
        <select
          {...common}
          value={defaultDraft}
          onChange={(e) => {
            setDefaultDraft(e.target.value);
            clearError("default_value");
          }}
        >
          <option value="">No default</option>
          {stale && <option value={defaultDraft}>{defaultDraft} (not allowed)</option>}
          {options.map((option) => (
            <option key={option} value={option}>
              {dataType === "boolean" ? (option === "true" ? "True" : "False") : option}
            </option>
          ))}
        </select>
      );
    }

    // `integer` and `number` use a text box in numeric input mode rather
    // than `type="number"`: a number input reports an unparseable entry
    // ("banana", or "2.5" where a browser applies step=1) as the empty
    // string, which here would silently mean "no default" instead of
    // being refused. The text box keeps what was typed visible to
    // `parseDefaultValue`, and phones still get a numeric keypad.
    const inputProps =
      dataType === "integer"
        ? { type: "text", inputMode: "numeric" as const }
        : dataType === "number"
          ? { type: "text", inputMode: "decimal" as const }
          : dataType === "date"
            ? { type: "date" }
            : dataType === "time"
              ? { type: "time" }
              : { type: "text" };
    return (
      <input
        {...common}
        {...inputProps}
        autoComplete="off"
        value={defaultDraft}
        onChange={(e) => {
          setDefaultDraft(e.target.value);
          clearError("default_value");
        }}
      />
    );
  }

  const defaultHint: Record<AttrType, string> = {
    integer: "A whole number, such as 8 or -2. Leave empty for no default.",
    number: "A number, such as 2.5. Leave empty for no default.",
    text: "Leave empty for no default.",
    boolean: "",
    enum: "One of the allowed values above.",
    time: "Leave empty for no default.",
    date: "Leave empty for no default.",
  };

  return (
    <form
      aria-label={formLabel ?? (isEdit ? `Edit attribute ${initial?.name}` : "New attribute")}
      onSubmit={handleSubmit}
      noValidate
      className="space-y-4"
    >
      <ErrorSummary errors={errors} order={FIELD_ORDER} summaryRef={summaryRef} />

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor={id("name")} required>
            Name
          </FieldLabel>
          <input
            ref={nameRef}
            id={id("name")}
            type="text"
            autoComplete="off"
            spellCheck={false}
            className={`${INPUT_CLASS} font-mono`}
            value={name}
            aria-invalid={errors.name ? "true" : undefined}
            aria-describedby={describedBy(id("name-hint"), errors.name && errorId("name"))}
            onChange={(e) => {
              setName(e.target.value);
              clearError("name");
            }}
          />
          <p id={id("name-hint")} className="mt-1 text-xs text-slate-500">
            Lowercase, e.g. <code>start_date</code>.
          </p>
          <FieldError id={errorId("name")} message={errors.name} />
        </div>

        <div>
          <FieldLabel htmlFor={id("data_type")} required>
            Data type
          </FieldLabel>
          <select
            id={id("data_type")}
            className={INPUT_CLASS}
            value={dataType}
            aria-invalid={errors.data_type ? "true" : undefined}
            aria-describedby={describedBy(errors.data_type && errorId("data_type"))}
            onChange={(e) => changeType(e.target.value as AttrType)}
          >
            {DATA_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <FieldError id={errorId("data_type")} message={errors.data_type} />
        </div>

        <div>
          <FieldLabel htmlFor={id("unit")}>Unit</FieldLabel>
          <input
            id={id("unit")}
            type="text"
            autoComplete="off"
            className={INPUT_CLASS}
            placeholder="e.g. hours"
            value={unit}
            aria-invalid={errors.unit ? "true" : undefined}
            aria-describedby={describedBy(errors.unit && errorId("unit"))}
            onChange={(e) => {
              setUnit(e.target.value);
              clearError("unit");
            }}
          />
          <FieldError id={errorId("unit")} message={errors.unit} />
        </div>

        <div className="flex items-center gap-2 sm:mt-7">
          <input
            id={id("required")}
            type="checkbox"
            className="h-6 w-6"
            checked={required}
            aria-invalid={errors.required ? "true" : undefined}
            aria-describedby={describedBy(errors.required && errorId("required"))}
            onChange={(e) => setRequired(e.target.checked)}
          />
          <label htmlFor={id("required")} className="text-sm font-medium text-slate-700">
            Required
          </label>
          <FieldError id={errorId("required")} message={errors.required} />
        </div>
      </div>

      {dataType === "enum" && (
        <div>
          <FieldLabel htmlFor={id("enum_values")} required>
            Allowed values
          </FieldLabel>
          <textarea
            id={id("enum_values")}
            rows={4}
            className={`${INPUT_CLASS} font-mono`}
            value={enumText}
            aria-invalid={errors.enum_values ? "true" : undefined}
            aria-describedby={describedBy(id("enum_values-hint"), errors.enum_values && errorId("enum_values"))}
            onChange={(e) => {
              setEnumText(e.target.value);
              clearError("enum_values");
            }}
          />
          <p id={id("enum_values-hint")} className="mt-1 text-xs text-slate-500">
            One per line.
          </p>
          <FieldError id={errorId("enum_values")} message={errors.enum_values} />
        </div>
      )}

      <div>
        <FieldLabel htmlFor={id("default_value")}>Default value</FieldLabel>
        {renderDefaultControl()}
        {defaultHint[dataType] && (
          <p id={id("default_value-hint")} className="mt-1 text-xs text-slate-500">
            {defaultHint[dataType]}
          </p>
        )}
        <p id={id("default_value-note")} className="mt-1 text-xs text-amber-800">
          {MATERIALISED_NOTE}
        </p>
        <FieldError id={errorId("default_value")} message={errors.default_value} />
      </div>

      {isEdit && (
        <p className="text-xs text-slate-600">
          Renaming this attribute, changing its type or removing an allowed value does not change values already
          stored on entities.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Saving…" : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-2 text-sm text-slate-600 underline hover:text-slate-900"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
