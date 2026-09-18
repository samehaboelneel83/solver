import type { AttributeDefinitionOption } from "../types/graph";
import { fromDatetimeLocalValue, toDatetimeLocalValue } from "../lib/datetime";

const INPUT_CLASS = "block w-full rounded-md border border-slate-300 px-2 py-1 text-sm";

/**
 * Attribute codes that collide with a node's built-in fields -- `name` is
 * always its own input, and `code`/`status`/`description` are always keys
 * in `GraphNode.attributes` set from the entity's own columns. The backend
 * (`get_domain_graph`/`_entity_to_node`) makes the built-in value win over
 * an EAV row using one of these codes, so an attribute definition that
 * collides would render an input whose edits are silently never reflected.
 * Hidden from the attribute inputs entirely instead, with a note.
 */
export const BUILTIN_ATTRIBUTE_CODES: ReadonlySet<string> = new Set(["code", "status", "description", "name"]);

/** Splits `definitions` into the ones safe to render (`visible`) and the
 * ones that collide with a built-in field (`hidden`), per
 * `BUILTIN_ATTRIBUTE_CODES` above. Shared by PropertyPanel and GraphEditor's
 * create-node form so both apply the same rule. */
export function splitBuiltinCollisions<T extends { code: string }>(
  definitions: T[]
): { visible: T[]; hidden: T[] } {
  const visible: T[] = [];
  const hidden: T[] = [];
  for (const def of definitions) {
    (BUILTIN_ATTRIBUTE_CODES.has(def.code) ? hidden : visible).push(def);
  }
  return { visible, hidden };
}

/**
 * Renders a form input appropriate for an attribute's `data_type` (Task 7's typed
 * coercion): number -> `type="number"`, boolean -> checkbox, date/datetime -> native
 * date/datetime-local inputs, json -> a textarea, anything else -> plain text. Shared by
 * PropertyPanel (editing) and GraphEditor's create-node form so both stay typed the same
 * way. Uncontrolled (defaultValue/defaultChecked) -- callers read the submitted value back
 * out of FormData with `attributeValueFromForm` below, matching the rest of these forms.
 */
export function AttributeInput({ def, defaultValue }: { def: AttributeDefinitionOption; defaultValue?: unknown }) {
  const name = `attr:${def.code}`;

  if (def.data_type === "boolean") {
    // H-9: a bare native checkbox renders at the browser default (~13x13px in Chromium), well
    // under the 24px Target Size floor -- found by a full app-wide sweep (the audit's own named
    // controls didn't include this one, since it only appears once a node/edge with a boolean
    // attribute is selected). h-6/w-6 sizes the checkbox itself to a full 24x24 hit area.
    return <input type="checkbox" name={name} defaultChecked={Boolean(defaultValue)} className="h-6 w-6" />;
  }
  if (def.data_type === "number") {
    return (
      <input
        type="number"
        name={name}
        defaultValue={defaultValue === undefined || defaultValue === null ? "" : String(defaultValue)}
        className={INPUT_CLASS}
      />
    );
  }
  if (def.data_type === "date") {
    return (
      <input
        type="date"
        name={name}
        defaultValue={typeof defaultValue === "string" ? defaultValue.slice(0, 10) : ""}
        className={INPUT_CLASS}
      />
    );
  }
  if (def.data_type === "datetime") {
    return (
      <input
        type="datetime-local"
        name={name}
        defaultValue={typeof defaultValue === "string" ? toDatetimeLocalValue(defaultValue) : ""}
        className={INPUT_CLASS}
      />
    );
  }
  if (def.data_type === "json") {
    return (
      <textarea
        name={name}
        rows={3}
        defaultValue={
          defaultValue === undefined || defaultValue === null ? "" : JSON.stringify(defaultValue, null, 2)
        }
        className={`${INPUT_CLASS} font-mono text-xs`}
      />
    );
  }
  return (
    <input
      type="text"
      name={name}
      defaultValue={defaultValue === undefined || defaultValue === null ? "" : String(defaultValue)}
      className={INPUT_CLASS}
    />
  );
}

/**
 * Reads one attribute's submitted value back out of FormData, coerced to match what the
 * backend expects for `def.data_type`:
 * - boolean: always `true`/`false` -- a checkbox has no "empty" state to distinguish from
 *   "clear", so it always sets rather than ever clearing.
 * - everything else: an empty/whitespace-only input becomes `null` ("clear this attribute",
 *   per Task 7's explicit-null semantics), `number` becomes a JS number (sent as a real JSON
 *   number -- throwing a plain Error, rather than letting a non-finite result through, when the
 *   text isn't a finite number: `Number("abc")` is `NaN` and `Number("1e400")` is `Infinity`,
 *   and `JSON.stringify` silently turns either into `null` in the request body, which would
 *   otherwise look identical to the user explicitly clearing the attribute -- a 200 that quietly
 *   deletes data instead of the 422 a bad value should produce), `json` is parsed (throwing a
 *   plain Error with a field-naming message on invalid JSON), `datetime` is converted from the
 *   input's naive local wall-clock string to an ISO UTC instant (the same conversion EntityForm
 *   uses), and date/string are passed through as the string the input gave.
 */
export function attributeValueFromForm(form: FormData, def: AttributeDefinitionOption): unknown {
  const name = `attr:${def.code}`;
  if (def.data_type === "boolean") {
    return form.get(name) === "on";
  }
  const raw = form.get(name);
  const rawStr = raw === null ? "" : String(raw);
  if (rawStr.trim() === "") {
    return null;
  }
  if (def.data_type === "number") {
    const num = Number(rawStr);
    if (!Number.isFinite(num)) {
      throw new Error(`${def.name}: expects a number`);
    }
    return num;
  }
  if (def.data_type === "datetime") {
    return fromDatetimeLocalValue(rawStr);
  }
  if (def.data_type === "json") {
    try {
      return JSON.parse(rawStr);
    } catch {
      throw new Error(`${def.name} must be valid JSON`);
    }
  }
  return rawStr;
}
