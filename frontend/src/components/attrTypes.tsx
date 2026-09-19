import { ReactNode, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { validationErrors, type AttrType, type EntityRole } from "../api/v1";

/*
 * The v1 attribute vocabulary and the form plumbing built on it, shared by
 * every screen that reads or writes `attribute_def` and `entity.attrs`:
 * the entity-type editor and its attribute form (Task 11), and the entity
 * record form (Task 12). It moved out of `AttributeDefEditor.tsx` when the
 * second consumer appeared -- the frontend twin of Ruling 22's
 * `validation.py` move -- so a value parser is not owned by whichever
 * component happened to need it first.
 *
 * The form conventions here are EntityForm's: a visible <label> per
 * control with a red, aria-hidden asterisk for required fields; an inline
 * `text-xs text-red-600` message that the control points at with
 * `aria-describedby`; `aria-invalid` on the control; and an error summary
 * (`role="alert"`, focused after a failed submit) listing every message.
 * EntityForm itself is metadata-driven (`FieldMeta` from /api/meta), which
 * these v1 tables are not, so the conventions are reused rather than the
 * component.
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
export function parseAttrValue(
  type: AttrType,
  raw: string,
  enumValues: string[],
  label: string
): ParsedDefault {
  if (raw === "") return { ok: true, value: null };
  const text = raw.trim();
  switch (type) {
    case "integer": {
      if (!INTEGER_RE.test(text)) {
        return { ok: false, message: `${label}: must be a whole number, such as 8 or -2 (no decimals).` };
      }
      const value = Number(text);
      if (!Number.isSafeInteger(value)) {
        return { ok: false, message: `${label}: this whole number is too large to store exactly.` };
      }
      return { ok: true, value };
    }
    case "number": {
      const value = Number(text);
      if (!NUMBER_RE.test(text) || !Number.isFinite(value)) {
        return { ok: false, message: `${label}: must be a number, such as 2.5.` };
      }
      return { ok: true, value };
    }
    case "boolean":
      if (raw === "true") return { ok: true, value: true };
      if (raw === "false") return { ok: true, value: false };
      return { ok: false, message: `${label}: must be True or False.` };
    case "enum":
      if (!enumValues.includes(raw)) {
        return { ok: false, message: `${label}: "${raw}" is not one of the allowed values.` };
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
      return { ok: false, message: `${label}: must be a date (YYYY-MM-DD).` };
    }
    case "time":
      if (!TIME_RE.test(text)) return { ok: false, message: `${label}: must be a time of day (HH:MM).` };
      return { ok: true, value: text };
    case "text":
    default:
      return { ok: true, value: raw };
  }
}

/** `parseAttrValue` with the attribute editor's own label, which is what
 * every message in this module said before the entity form needed the same
 * parser under a different name. */
export function parseDefaultValue(type: AttrType, raw: string, enumValues: string[]): ParsedDefault {
  return parseAttrValue(type, raw, enumValues, "Default value");
}

/** A stored default as the text its input holds. A value of the wrong JSON
 * type (one saved before this editor, or through the API) is shown as-is
 * rather than hidden, so the user can see it and replace it. */
export function draftFromValue(value: unknown): string {
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

