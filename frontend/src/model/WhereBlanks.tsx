/**
 * "Only some of them": the conditions on a binding, editable in words in the
 * Sentence and Boxes views.
 *
 *   every [person ▾] [p] whose [team ▾] [is ▾] [north] and [cap ▾] [is at least ▾] [2] ✕
 *
 * A binding's `where` is a list of conditions that must all hold, each one a
 * condition or a group of alternatives ("or"), one level deep; "is one of"
 * covers "this or that" for one attribute. The comparisons offered follow the
 * attribute's type, and the value box fits it: a number, yes/no, text, or a
 * comma-separated list for "is one of".
 */
import { useEffect, useState } from "react";
import { isGroup, isIndexFilter, type IrFilter, type ModelContext, type WhereEntry } from "./terms";
import { defaultValue, isList, NUMBER_TYPES, opsFor, OP_WORDS, valueWords } from "./whereWords";
import { entryWords } from "./whereWords";

function parseOne(text: string, dataType: string | undefined): unknown {
  if (dataType && NUMBER_TYPES.includes(dataType)) {
    const n = Number(text);
    return text.trim() !== "" && Number.isFinite(n) ? n : text;
  }
  return text;
}

function ValueBlank({ label, filter, dataType, choices, className, onChange }: {
  label: string;
  filter: IrFilter;
  dataType: string | undefined;
  /** A list-of-choices attribute's choices: picked, not typed. */
  choices?: string[] | null;
  className: string;
  onChange: (value: unknown) => void;
}) {
  const shown = Array.isArray(filter.value) ? filter.value.map(valueWords).join(", ") : valueWords(filter.value);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  if (choices && choices.length > 0) {
    if (isList(filter.op)) {
      const picked = Array.isArray(filter.value) ? filter.value.map(String) : [];
      return (
        <span role="group" aria-label={label} className="inline-flex flex-wrap items-center gap-2 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-sm">
          {choices.map((choice) => (
            <label key={choice} className="inline-flex items-center gap-1">
              <input type="checkbox" checked={picked.includes(choice)}
                onChange={(event) => onChange(event.target.checked ? choices.filter((c) => c === choice || picked.includes(c)) : picked.filter((c) => c !== choice))} />
              {choice}
            </label>
          ))}
        </span>
      );
    }
    const value = String(filter.value ?? "");
    return (
      <select aria-label={label} className={className} value={value} onChange={(event) => onChange(event.target.value)}>
        {!choices.includes(value) && <option value={value}>{value || "choose…"}</option>}
        {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
      </select>
    );
  }
  if ((dataType === "date" || dataType === "time") && !isList(filter.op)) {
    return (
      <input type={dataType} aria-label={label} className={className} value={typeof filter.value === "string" ? filter.value : ""}
        onChange={(event) => onChange(event.target.value)} />
    );
  }
  if (dataType === "boolean" && !isList(filter.op)) {
    return (
      <select aria-label={label} className={className} value={filter.value === false ? "no" : "yes"}
        onChange={(event) => onChange(event.target.value === "yes")}>
        <option value="yes">yes</option>
        <option value="no">no</option>
      </select>
    );
  }
  const list = isList(filter.op);
  const numeric = !!dataType && NUMBER_TYPES.includes(dataType);
  return (
    <input aria-label={label} className={`${className} ${list ? "w-36" : numeric ? "w-16 font-mono" : "w-24"}`}
      inputMode={numeric && !list ? "decimal" : undefined}
      placeholder={list ? "a, b, c" : undefined} value={text}
      onChange={(event) => {
        setText(event.target.value);
        onChange(list
          ? event.target.value.split(",").map((part) => part.trim()).filter((part) => part !== "").map((part) => parseOne(part, dataType))
          : parseOne(event.target.value, dataType));
      }} />
  );
}

type Attribute = { name: string; data_type: string; enum_values?: string[] | null };

/** One condition: [attribute ▾] [comparison ▾] [value] ✕, and "or…" to add an alternative. */
function ConditionBlanks({ name, filter, attributes, className, onChange, onRemove, onOr }: {
  name: string;
  filter: IrFilter;
  attributes: Attribute[];
  className: string;
  onChange: (next: IrFilter) => void;
  onRemove: () => void;
  onOr?: () => void;
}) {
  const typeOf = (attr: string) => attributes.find((a) => a.name === attr)?.data_type;
  const choicesOf = (attr: string) => attributes.find((a) => a.name === attr)?.enum_values;
  const start = (attr: string, op: string) => startValue(attributes, attr, op);
  const dataType = typeOf(filter.attr);
  const ops = opsFor(dataType);
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="where-condition">
      <select aria-label={`${name}: attribute`} className={className} value={filter.attr}
        onChange={(event) => {
          const attr = event.target.value;
          const op = opsFor(typeOf(attr)).includes(filter.op) ? filter.op : "=";
          onChange({ attr, op, value: start(attr, op) });
        }}>
        {!attributes.some((a) => a.name === filter.attr) && <option value={filter.attr}>{filter.attr || "choose…"}</option>}
        {attributes.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
      </select>
      <select aria-label={`${name}: comparison`} className={className} value={filter.op}
        onChange={(event) => {
          const op = event.target.value;
          // Moving between one value and a list keeps what was typed.
          const value = isList(op) === isList(filter.op)
            ? filter.value
            : isList(op)
              ? (filter.value === "" ? [] : [filter.value])
              : (Array.isArray(filter.value) && filter.value.length > 0 ? filter.value[0] : start(filter.attr, op));
          onChange({ ...filter, op, value });
        }}>
        {!ops.includes(filter.op) && <option value={filter.op}>{OP_WORDS[filter.op] ?? filter.op}</option>}
        {ops.map((op) => <option key={op} value={op}>{OP_WORDS[op]}</option>)}
      </select>
      <ValueBlank label={`${name}: value`} filter={filter} dataType={dataType} choices={choicesOf(filter.attr)} className={className}
        onChange={(value) => onChange({ ...filter, value })} />
      <button type="button" className="text-xs text-rose-700" aria-label={`Remove ${name}`} title="Remove this condition" onClick={onRemove}>
        ✕
      </button>
      {onOr && (
        <button type="button" className="text-xs text-blue-700 underline" aria-label={`Or: another way for ${name}`} title="Another way this condition can hold" onClick={onOr}>
          or…
        </button>
      )}
    </span>
  );
}

/** A starting value; a list of choices starts at its first choice. */
function startValue(attributes: Attribute[], attr: string, op: string): unknown {
  const found = attributes.find((a) => a.name === attr);
  return found?.enum_values?.length && !isList(op) ? found.enum_values[0] : defaultValue(found?.data_type, op);
}

/**
 * The conditions of one binding. `label` names the binding ("for each: set
 * 1"); each control is named from it ("for each: set 1: condition 2: value",
 * and in a group "…: condition 2 or 1: value"). An empty list is reported as
 * `undefined`, so `where` leaves the binding.
 *
 * Conditions are joined with "and"; "or…" beside one turns it into a group,
 * "(team is north or cap is at least 2)", that holds when any of its
 * conditions does. A group left with one condition is that condition again.
 *
 * `attributes` overrides the set's own (a walk's conditions on its links use
 * the relationship's); `addText` names the add button.
 */
export function WhereBlanks({ label, set, where, context, onChange, className, lead = "whose", attributes: given, addText }: {
  label: string;
  set: string;
  where: WhereEntry[] | undefined;
  context: ModelContext;
  onChange: (next: WhereEntry[] | undefined) => void;
  className: string;
  lead?: string;
  attributes?: Attribute[];
  addText?: [string, string];
}) {
  const attributes = given ?? context.attributes[set] ?? [];
  const entries = where ?? [];
  const setAll = (next: WhereEntry[]) => onChange(next.length > 0 ? next : undefined);
  const replace = (i: number, next: WhereEntry) => setAll(entries.map((e, j) => (j === i ? next : e)));
  const fresh = (): IrFilter => ({ attr: attributes[0].name, op: "=", value: startValue(attributes, attributes[0].name, "=") });

  return (
    <>
      {entries.map((entry, i) => {
        const name = `${label}: condition ${i + 1}`;
        const joiner = <span className="text-slate-600">{i === 0 ? ` ${lead} ` : " and "}</span>;
        if (isIndexFilter(entry)) {
          // Another item ("after a"): shown as written; changed in the formula, removed here.
          return (
            <span key={i} className="inline-flex flex-wrap items-center gap-1">
              {joiner}
              <span className="rounded bg-slate-100 px-1 font-mono text-xs">{entryWords(entry)}</span>
              <button type="button" aria-label={`Remove ${name}`} className="text-xs text-red-700 underline"
                onClick={() => setAll(entries.filter((_, j) => j !== i))}>remove</button>
            </span>
          );
        }
        if (!isGroup(entry)) {
          return (
            <span key={i} className="inline-flex flex-wrap items-center gap-1">
              {joiner}
              <ConditionBlanks name={name} filter={entry} attributes={attributes} className={className}
                onChange={(next) => replace(i, next)}
                onRemove={() => setAll(entries.filter((_, j) => j !== i))}
                onOr={() => replace(i, { any: [entry, fresh()] })} />
            </span>
          );
        }
        const setGroup = (any: IrFilter[]) => replace(i, any.length === 1 ? any[0] : { any });
        return (
          <span key={i} className="inline-flex flex-wrap items-center gap-1" role="group" aria-label={`${name}: any of`}>
            {joiner}
            <span className="text-slate-500">(</span>
            {entry.any.map((filter, g) => (
              <span key={g} className="inline-flex flex-wrap items-center gap-1">
                {g > 0 && <span className="text-slate-600">or</span>}
                <ConditionBlanks name={`${name} or ${g + 1}`} filter={filter} attributes={attributes} className={className}
                  onChange={(next) => setGroup(entry.any.map((f, k) => (k === g ? next : f)))}
                  onRemove={() => setGroup(entry.any.filter((_, k) => k !== g))} />
              </span>
            ))}
            <button type="button" className="text-xs text-blue-700 underline" aria-label={`Or: another way for ${name}`}
              onClick={() => setGroup([...entry.any, fresh()])}>
              + or
            </button>
            <span className="text-slate-500">)</span>
          </span>
        );
      })}
      {attributes.length > 0 && (
        <button type="button" className="ml-1 text-xs text-blue-700 underline" aria-label={`Only some of ${set}: add a condition to ${label}`}
          onClick={() => setAll([...entries, fresh()])}>
          {entries.length === 0 ? (addText?.[0] ?? "+ only some of them") : (addText?.[1] ?? "+ and")}
        </button>
      )}
    </>
  );
}
