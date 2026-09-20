import { useId } from "react";
import {
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  describedBy,
  draftFromValue,
  parseAttrValue,
  type FieldErrors,
} from "./attrTypes";
import type { AttrType, AttributeDef } from "../api/v1";

/**
 * The typed part of an entity form: one control per `attribute_def` row of
 * the entity's type, in the order the API returns them.
 *
 * Three things about `entity.attrs` shape everything here.
 *
 * 1. **The form rebuilds `attrs`; it never merges it.** `attrs` is one
 *    JSONB column and PATCH replaces it wholesale, and the validating
 *    trigger refuses any key with no `attribute_def` row (422,
 *    `kind="unknown_attribute"`). Deleting an attribute definition leaves
 *    its key on every entity that held a value, so an entity loaded
 *    before that deletion would be unsaveable if the form sent back what
 *    it loaded. `buildAttrs` therefore iterates the **definitions**, not
 *    the stored object, and the stale key disappears on the next save.
 *    `staleAttrKeys` names what is about to go, so it is not a silent
 *    data loss.
 *
 * 2. **An empty control omits its key rather than sending null.** The
 *    `entity_validate` trigger materialises `attribute_def.default_value`
 *    only when the key is *absent* (`v IS NULL`); an explicit JSON null is
 *    a present-but-null value, which stores a null and skips the default.
 *    So "no value" has to mean "no key". The consequence is that an empty
 *    string is not expressible through this form for a `text` attribute --
 *    an empty box means "not provided" for every type, uniformly.
 *
 * 3. **Falsy values are values.** `false`, `0` and `""` all round-trip;
 *    nothing here tests a value for truthiness.
 *
 * Numbers use a text box in numeric input mode rather than
 * `<input type="number">`, for the reason Task 11 recorded: a number input
 * reports an unparseable entry as `""`, which is indistinguishable from an
 * empty one, so `2.5` in an integer field would silently become "no
 * value". `date` and `time` are native inputs; `boolean` and `enum` are
 * selects, because a checkbox cannot express "not set" and an optional
 * boolean must be omittable for its default to materialise.
 */

/** What each control holds, keyed by attribute name. Always text: the
 * conversion to JSON happens once, in `buildAttrs`, so a half-typed entry
 * is never silently coerced. */
export type AttrDrafts = Record<string, string>;

/** Attribute errors share one `FieldErrors` map with the entity's own
 * columns, so they are namespaced: an attribute may legally be called
 * `key` or `label`. */
export function attrField(name: string): string {
  return `attr:${name}`;
}

/** The stored object as the controls' text, one entry per **current**
 * definition -- a key whose definition has been deleted never becomes a
 * draft, which is what makes `buildAttrs` drop it. */
export function draftsFromAttrs(attributes: AttributeDef[], attrs: Record<string, unknown>): AttrDrafts {
  const drafts: AttrDrafts = {};
  for (const attribute of attributes) {
    drafts[attribute.name] = draftFromValue(attrs?.[attribute.name]);
  }
  return drafts;
}

/** Stored keys no current definition covers, in the order the row holds
 * them. Each is about to be dropped by the next save. */
export function staleAttrKeys(attributes: AttributeDef[], attrs: Record<string, unknown>): string[] {
  const defined = new Set(attributes.map((attribute) => attribute.name));
  return Object.keys(attrs ?? {}).filter((key) => !defined.has(key));
}

export type BuiltAttrs =
  | { ok: true; attrs: Record<string, unknown> }
  | { ok: false; errors: FieldErrors };

/** The `attrs` object to send, or a message per control that cannot be
 * converted. Every control is reported, not just the first. */
export function buildAttrs(attributes: AttributeDef[], drafts: AttrDrafts): BuiltAttrs {
  const attrs: Record<string, unknown> = {};
  const errors: FieldErrors = {};
  for (const attribute of attributes) {
    const raw = drafts[attribute.name] ?? "";
    if (raw === "") {
      // A required attribute that carries a default is satisfied by the
      // trigger materialising it, so only a required attribute with no
      // default is refused here. `false` and `0` are defaults.
      if (attribute.required && !hasDefault(attribute)) {
        errors[attrField(attribute.name)] = `${attribute.name}: a value is required.`;
      }
      continue;
    }
    const parsed = parseAttrValue(attribute.data_type, raw, attribute.enum_values ?? [], attribute.name);
    if (parsed.ok) {
      attrs[attribute.name] = parsed.value;
    } else {
      errors[attrField(attribute.name)] = parsed.message;
    }
  }
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, attrs };
}

function hasDefault(attribute: AttributeDef): boolean {
  return attribute.default_value !== null && attribute.default_value !== undefined;
}

/** A stored value for a table cell or a hint. `false` and `0` are shown,
 * not blanked; an empty string is shown as such rather than as nothing at
 * all, so it is distinguishable from an absent value. */
export function formatAttrValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (value === true) return "Yes";
  if (value === false) return "No";
  if (typeof value === "string") return value === "" ? "(empty)" : value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

const TYPE_HINT: Record<AttrType, string> = {
  integer: "A whole number, such as 8 or -2.",
  number: "A number, such as 2.5.",
  text: "",
  boolean: "",
  enum: "",
  date: "",
  time: "",
};

function hintFor(attribute: AttributeDef): string {
  const parts = [TYPE_HINT[attribute.data_type]];
  if (hasDefault(attribute)) {
    parts.push(`Leave empty to use the default (${formatAttrValue(attribute.default_value)}).`);
  } else if (!attribute.required) {
    parts.push("Leave empty for no value.");
  }
  return parts.filter(Boolean).join(" ");
}

type AttrsFormProps = {
  /** In the API's order; the form does not re-sort them. */
  attributes: AttributeDef[];
  drafts: AttrDrafts;
  errors: FieldErrors;
  /** Stored keys with no definition left (see `staleAttrKeys`). */
  staleKeys?: string[];
  onChange: (name: string, value: string) => void;
};

export default function AttrsForm({ attributes, drafts, errors, staleKeys = [], onChange }: AttrsFormProps) {
  const baseId = useId();

  if (attributes.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        This entity type has no attributes yet, so an entity of it carries only a key and a label.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {staleKeys.length > 0 && (
        <p data-testid="stale-attrs" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          This entity still holds {staleKeys.length === 1 ? "a value" : "values"} for{" "}
          <span className="font-mono">{staleKeys.join(", ")}</span>, which{" "}
          {staleKeys.length === 1 ? "is" : "are"} no longer defined for this type.{" "}
          {staleKeys.length === 1 ? "It" : "They"} will be removed when you save.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {attributes.map((attribute) => {
          const id = `${baseId}-${attribute.name}`;
          const errorId = `${id}-error`;
          const hintId = `${id}-hint`;
          const hint = hintFor(attribute);
          const message = errors[attrField(attribute.name)];
          const draft = drafts[attribute.name] ?? "";
          const common = {
            id,
            "data-testid": `attr-${attribute.name}`,
            "aria-invalid": message ? ("true" as const) : undefined,
            "aria-describedby": describedBy(hint && hintId, message && errorId),
            className: INPUT_CLASS,
            value: draft,
            onChange: (event: { target: { value: string } }) => onChange(attribute.name, event.target.value),
          };
          return (
            <div key={attribute.id}>
              <FieldLabel htmlFor={id} required={attribute.required}>
                <span className="font-mono">{attribute.name}</span>
                {attribute.unit ? ` (${attribute.unit})` : ""}
              </FieldLabel>
              <Control attribute={attribute} draft={draft} common={common} />
              {hint && (
                <p id={hintId} className="mt-1 text-xs text-slate-500">
                  {hint}
                </p>
              )}
              <FieldError id={errorId} message={message} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function Control({ attribute, draft, common }: { attribute: AttributeDef; draft: string; common: any }) {
  if (attribute.data_type === "boolean" || attribute.data_type === "enum") {
    const options =
      attribute.data_type === "boolean"
        ? [
            { value: "true", label: "Yes" },
            { value: "false", label: "No" },
          ]
        : (attribute.enum_values ?? []).map((value) => ({ value, label: value }));
    // A value stored before an allowed value was dropped (or before the
    // type changed) is shown rather than silently replaced by the first
    // option -- `buildAttrs` then refuses it, so it cannot be saved back
    // unnoticed.
    const stale = draft !== "" && !options.some((option) => option.value === draft);
    return (
      <select {...common}>
        <option value="">No value</option>
        {stale && <option value={draft}>{draft} (not allowed)</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  const typeProps =
    attribute.data_type === "integer"
      ? { type: "text", inputMode: "numeric" as const }
      : attribute.data_type === "number"
        ? { type: "text", inputMode: "decimal" as const }
        : attribute.data_type === "date"
          ? { type: "date" }
          : attribute.data_type === "time"
            ? { type: "time" }
            : { type: "text" };
  return <input {...common} {...typeProps} autoComplete="off" />;
}
