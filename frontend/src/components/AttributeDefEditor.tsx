import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { type AttrType, type AttributeDef, type AttributeDefCreate } from "../api/v1";
import {
  DATA_TYPES,
  ErrorSummary,
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  describedBy,
  draftFromValue,
  nameProblem,
  parseDefaultValue,
  useFieldErrors,
  type FieldErrors,
} from "./attrTypes";

/*
 * The attribute-definition form. Its vocabulary, value parsing and form
 * plumbing live in `attrTypes.tsx`, shared with the entity record form
 * (Task 12); what is left here is the editor itself.
 */

// --- the editor -------------------------------------------------------------------

/** The "allowed values" textarea, one value per line: blank lines dropped,
 * each value trimmed. Only this editor writes `enum_values`, so it stays
 * here rather than moving to `attrTypes`. */
function parseEnumValues(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

const FIELD_ORDER = ["name", "data_type", "required", "unit", "sort_order", "enum_values", "default_value"];
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
  // Text, not a number, so an empty box can mean "after the others" on a new
  // attribute and "unchanged" on an existing one (migration 0027).
  const [sortOrder, setSortOrder] = useState(initial ? String(initial.sort_order) : "");
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

    const trimmedOrder = sortOrder.trim();
    const order = trimmedOrder === "" ? null : Number(trimmedOrder);
    if (order !== null && !(Number.isInteger(order) && Math.abs(order) <= 2 ** 31 - 1)) {
      next.sort_order = "Sort order: a whole number, or leave it empty.";
    }

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
      // Omitted rather than null: the server reads an absent position as
      // "after the others" on create and "unchanged" on edit, and refuses a
      // null for a column that is never empty.
      ...(order === null ? {} : { sort_order: order }),
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
    geometry: "GeoJSON; usually left empty -- each record draws its own shape.",
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

        <div>
          <FieldLabel htmlFor={id("sort_order")}>Sort order</FieldLabel>
          <input
            id={id("sort_order")}
            type="number"
            inputMode="numeric"
            step={1}
            className={INPUT_CLASS}
            placeholder={initial ? "" : "after the others"}
            value={sortOrder}
            aria-invalid={errors.sort_order ? "true" : undefined}
            aria-describedby={describedBy(id("sort_order-hint"), errors.sort_order && errorId("sort_order"))}
            onChange={(e) => {
              setSortOrder(e.target.value);
              clearError("sort_order");
            }}
          />
          <p id={id("sort_order-hint")} className="mt-1 text-xs text-slate-500">
            Lower comes first in forms and lists. Ties go by name.
          </p>
          <FieldError id={errorId("sort_order")} message={errors.sort_order} />
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
