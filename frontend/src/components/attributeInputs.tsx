import type { AttributeDefinitionOption } from "../types/graph";

const INPUT_CLASS = "block w-full rounded-md border border-slate-300 px-2 py-1 text-sm";

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
    return <input type="checkbox" name={name} defaultChecked={Boolean(defaultValue)} />;
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
        defaultValue={typeof defaultValue === "string" ? defaultValue.slice(0, 16) : ""}
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
 *   number), `json` is parsed (throwing a plain Error with a field-naming message on invalid
 *   JSON), and date/datetime/string are passed through as the string the input gave.
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
    return Number(rawStr);
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
