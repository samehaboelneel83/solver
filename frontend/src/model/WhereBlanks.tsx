/**
 * "Only some of them": the conditions on a binding, editable in words in the
 * Sentence and Boxes views.
 *
 *   every [person ▾] [p] whose [team ▾] [is ▾] [north] and [cap ▾] [is at least ▾] [2] ✕
 *
 * A binding's `where` is a flat list of conditions that must all hold (the
 * IR has no groups and no "or"), so that is all this offers; "is one of"
 * covers "this or that" for one attribute. The comparisons offered follow the
 * attribute's type, and the value box fits it: a number, yes/no, text, or a
 * comma-separated list for "is one of".
 */
import { useEffect, useState } from "react";
import type { IrFilter, ModelContext } from "./terms";
import { defaultValue, isList, NUMBER_TYPES, opsFor, OP_WORDS, valueWords } from "./whereWords";

function parseOne(text: string, dataType: string | undefined): unknown {
  if (dataType && NUMBER_TYPES.includes(dataType)) {
    const n = Number(text);
    return text.trim() !== "" && Number.isFinite(n) ? n : text;
  }
  return text;
}

function ValueBlank({ label, filter, dataType, className, onChange }: {
  label: string;
  filter: IrFilter;
  dataType: string | undefined;
  className: string;
  onChange: (value: unknown) => void;
}) {
  const shown = Array.isArray(filter.value) ? filter.value.map(valueWords).join(", ") : valueWords(filter.value);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
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

/**
 * The conditions of one binding. `label` names the binding ("for each: set
 * 1"); each control is named from it ("for each: set 1: condition 2: value").
 * An empty list is reported as `undefined`, so `where` leaves the binding.
 */
export function WhereBlanks({ label, set, where, context, onChange, className, lead = "whose" }: {
  label: string;
  set: string;
  where: IrFilter[] | undefined;
  context: ModelContext;
  onChange: (next: IrFilter[] | undefined) => void;
  className: string;
  lead?: string;
}) {
  const attributes = context.attributes[set] ?? [];
  const filters = where ?? [];
  const typeOf = (attr: string) => attributes.find((a) => a.name === attr)?.data_type;
  const setAll = (next: IrFilter[]) => onChange(next.length > 0 ? next : undefined);
  const replace = (i: number, next: IrFilter) => setAll(filters.map((f, j) => (j === i ? next : f)));

  return (
    <>
      {filters.map((filter, i) => {
        const name = `${label}: condition ${i + 1}`;
        const dataType = typeOf(filter.attr);
        const ops = opsFor(dataType);
        return (
          <span key={i} className="inline-flex flex-wrap items-center gap-1" data-testid="where-condition">
            <span className="text-slate-600">{i === 0 ? ` ${lead} ` : " and "}</span>
            <select aria-label={`${name}: attribute`} className={className} value={filter.attr}
              onChange={(event) => {
                const attr = event.target.value;
                const type = typeOf(attr);
                const op = opsFor(type).includes(filter.op) ? filter.op : "=";
                replace(i, { attr, op, value: defaultValue(type, op) });
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
                    : (Array.isArray(filter.value) && filter.value.length > 0 ? filter.value[0] : defaultValue(dataType, op));
                replace(i, { ...filter, op, value });
              }}>
              {!ops.includes(filter.op) && <option value={filter.op}>{OP_WORDS[filter.op] ?? filter.op}</option>}
              {ops.map((op) => <option key={op} value={op}>{OP_WORDS[op]}</option>)}
            </select>
            <ValueBlank label={`${name}: value`} filter={filter} dataType={dataType} className={className}
              onChange={(value) => replace(i, { ...filter, value })} />
            <button type="button" className="text-xs text-rose-700" aria-label={`Remove ${name}`} title="Remove this condition"
              onClick={() => setAll(filters.filter((_, j) => j !== i))}>
              ✕
            </button>
          </span>
        );
      })}
      {attributes.length > 0 && (
        <button type="button" className="ml-1 text-xs text-blue-700 underline" aria-label={`Only some of ${set}: add a condition to ${label}`}
          onClick={() => {
            const first = attributes[0];
            setAll([...filters, { attr: first.name, op: "=", value: defaultValue(first.data_type, "=") }]);
          }}>
          {filters.length === 0 ? "+ only some of them" : "+ and"}
        </button>
      )}
    </>
  );
}
