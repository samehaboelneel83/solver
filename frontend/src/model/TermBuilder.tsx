import { useId } from "react";
import ExpressionBuilder from "../expressions/ExpressionBuilder";
import { buildFieldCatalogue } from "../expressions";
import { INPUT_CLASS } from "../components/attrTypes";
import { TERM_KINDS } from "../ir/contract";
import type { TermKind } from "../ir";
import {
  boundIndices,
  describeTerm,
  emptyTerm,
  freeIndexName,
  integerAttributes,
  mentionsVariable,
  TERM_LABELS,
  termKind,
  type Binding,
  type ModelContext,
  type Term,
} from "./terms";
import { fromIrWhere, toIrWhere } from "./whereFilter";

/**
 * Editing one term of a model, and the bindings it ranges over.
 *
 * The two halves meet here: **react-querybuilder edits every `where`
 * filter** (a boolean condition tree, which is exactly what it is for) and
 * this edits the arithmetic around it (which is not, see `terms.ts`).
 *
 * Every control offers only what the context allows — a parameter's
 * subscripts offer the indices bound to the right set at that position, an
 * attribute offers `integer` ones only — so the editor cannot build a term
 * the contract would refuse. Where it still can (a product of two variable
 * terms), it says so inline rather than letting the server answer.
 */

export type TermBuilderProps = {
  value: Term;
  onChange: (term: Term) => void;
  context: ModelContext;
  /** Indices already bound by an enclosing `forall` or `sum`. */
  bound: Binding[];
  /** Nesting depth, for the heading level and the indent. */
  depth?: number;
  label?: string;
};

export default function TermBuilder({
  value,
  onChange,
  context,
  bound,
  depth = 0,
  label,
}: TermBuilderProps) {
  const kindId = useId();
  const kind = termKind(value);

  return (
    <div className={depth > 0 ? "border-l-2 border-slate-200 pl-3" : ""}>
      <div className="flex flex-wrap items-center gap-2">
        {label && <span className="text-xs font-medium text-slate-600">{label}</span>}
        <label htmlFor={kindId} className="sr-only">
          {label ? `${label}: kind of term` : "Kind of term"}
        </label>
        <select
          id={kindId}
          className={`${INPUT_CLASS} w-auto text-xs`}
          value={kind}
          onChange={(event) =>
            onChange(emptyTerm(event.target.value as TermKind, context, bound))
          }
        >
          {TERM_KINDS.map((option) => (
            <option key={option} value={option}>
              {TERM_LABELS[option]}
            </option>
          ))}
        </select>
        <span className="font-mono text-xs text-slate-500">{describeTerm(value)}</span>
      </div>

      <div className="mt-2">
        <Body value={value} onChange={onChange} context={context} bound={bound} depth={depth} />
      </div>
    </div>
  );
}

function Body({ value, onChange, context, bound, depth }: Required<Omit<TermBuilderProps, "label">>) {
  const kind = termKind(value);

  if (kind === "const") {
    const term = value as { const: number };
    return (
      <NumberField
        label="Value"
        value={term.const}
        onChange={(next) => onChange({ const: next })}
      />
    );
  }

  if (kind === "par" || kind === "var") {
    const isVar = kind === "var";
    const term = value as { par?: string; var?: string; index: string[] };
    const name = (isVar ? term.var : term.par) ?? "";
    const declarations = isVar ? context.variables : context.parameters;
    const wantedSets = declarations[name]?.index ?? [];

    return (
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label={isVar ? "Variable" : "Parameter"}
          value={name}
          options={Object.keys(declarations).map((n) => ({ value: n, label: n }))}
          onChange={(next) => {
            const arity = declarations[next]?.index.length ?? 0;
            const indices = Array.from({ length: arity }, (_, position) => {
              const set = declarations[next]?.index[position];
              return bound.find((b) => b.set === set)?.index ?? "";
            });
            onChange(isVar ? { var: next, index: indices } : { par: next, index: indices });
          }}
        />
        {wantedSets.map((set, position) => (
          <Select
            key={`${name}-${position}`}
            label={`${set} index`}
            value={term.index[position] ?? ""}
            options={bound
              .filter((b) => b.set === set)
              .map((b) => ({ value: b.index, label: `${b.index} in ${b.set}` }))}
            emptyLabel={`no index over ${set}`}
            onChange={(next) => {
              const indices = [...term.index];
              indices[position] = next;
              onChange(isVar ? { var: name, index: indices } : { par: name, index: indices });
            }}
          />
        ))}
      </div>
    );
  }

  if (kind === "attr") {
    const term = value as { attr: { of: string; name: string } };
    const binding = bound.find((b) => b.index === term.attr.of);
    const attributes = binding ? integerAttributes(context, binding.set) : [];
    return (
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label="Of"
          value={term.attr.of}
          options={bound.map((b) => ({ value: b.index, label: `${b.index} in ${b.set}` }))}
          emptyLabel="nothing is bound here"
          onChange={(next) => onChange({ attr: { of: next, name: "" } })}
        />
        <Select
          label="Attribute"
          value={term.attr.name}
          options={attributes.map((a) => ({ value: a.name, label: a.name }))}
          emptyLabel={binding ? `${binding.set} has no whole-number attribute` : "choose an index first"}
          onChange={(next) => onChange({ attr: { of: term.attr.of, name: next } })}
        />
        {binding && attributes.length === 0 && (
          <p className="text-xs text-slate-500">
            Arithmetic uses whole-number attributes only, so a decimal one cannot appear here.
          </p>
        )}
      </div>
    );
  }

  if (kind === "sum") {
    const term = value as { sum: Term; over: Binding[] };
    const inner = boundIndices(bound, term.over);
    return (
      <div className="space-y-3">
        <BindingsEditor
          bindings={term.over}
          onChange={(over) => onChange({ sum: term.sum, over })}
          context={context}
          outer={bound}
          legend="Summed over"
        />
        <TermBuilder
          value={term.sum}
          onChange={(next) => onChange({ sum: next, over: term.over })}
          context={context}
          bound={inner}
          depth={depth + 1}
          label="Of"
        />
      </div>
    );
  }

  if (kind === "add") {
    const term = value as { add: Term[] };
    return (
      <div className="space-y-2">
        {term.add.map((part, position) => (
          <div key={position} className="flex items-start gap-2">
            <TermBuilder
              value={part}
              onChange={(next) => {
                const parts = [...term.add];
                parts[position] = next;
                onChange({ add: parts });
              }}
              context={context}
              bound={bound}
              depth={depth + 1}
              label={position === 0 ? "First" : "Plus"}
            />
            {term.add.length > 2 && (
              <button
                type="button"
                className="rounded px-2 py-1 text-xs text-red-700 underline"
                onClick={() => onChange({ add: term.add.filter((_, i) => i !== position) })}
              >
                Remove
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className="rounded px-2 py-1 text-xs text-blue-700 underline"
          onClick={() => onChange({ add: [...term.add, { const: 0 }] })}
        >
          Add another term
        </button>
      </div>
    );
  }

  const term = value as { mul: [Term, Term] };
  const bothHaveVariables = mentionsVariable(term.mul[0]) && mentionsVariable(term.mul[1]);
  return (
    <div className="space-y-2">
      {bothHaveVariables && (
        <p role="alert" className="text-xs text-red-600">
          Both sides use a variable, so this is not linear. One side must be a number, a parameter
          or an attribute.
        </p>
      )}
      {[0, 1].map((position) => (
        <TermBuilder
          key={position}
          value={term.mul[position]}
          onChange={(next) => {
            const factors: [Term, Term] = [...term.mul] as [Term, Term];
            factors[position] = next;
            onChange({ mul: factors });
          }}
          context={context}
          bound={bound}
          depth={depth + 1}
          label={position === 0 ? "This" : "Times"}
        />
      ))}
    </div>
  );
}

export type BindingsEditorProps = {
  bindings: Binding[];
  onChange: (bindings: Binding[]) => void;
  context: ModelContext;
  /** Indices bound further out, so a new one does not shadow them. */
  outer: Binding[];
  legend: string;
};

/**
 * The bindings of a `forall` or a `sum`, each with an optional filter.
 *
 * The filter is a **react-querybuilder** document, converted to the IR's
 * flat and-list on save. The builder can express more than the IR admits —
 * `or`, nesting, negation — and `whereFilter.ts` refuses those with the
 * reason rather than flattening them, because flattening would change which
 * entities the constraint ranges over.
 */
export function BindingsEditor({ bindings, onChange, context, outer, legend }: BindingsEditorProps) {
  return (
    <fieldset className="rounded border border-slate-200 p-2">
      <legend className="px-1 text-xs font-medium text-slate-600">{legend}</legend>
      <div className="space-y-3">
        {bindings.map((binding, position) => {
          const others = [...outer, ...bindings.filter((_, i) => i !== position)];
          const setId = context.setIds[binding.set];
          const attributes = context.attributes[binding.set] ?? [];
          return (
            <div key={position} className="space-y-2 rounded bg-slate-50 p-2">
              <div className="flex flex-wrap items-end gap-2">
                <TextField
                  label="Index"
                  value={binding.index}
                  onChange={(next) => replace(position, { ...binding, index: next })}
                />
                <Select
                  label="Over"
                  value={binding.set}
                  options={context.sets.map((s) => ({ value: s, label: s }))}
                  onChange={(next) => replace(position, { ...binding, set: next, where: [] })}
                />
                {bindings.length > 1 && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-xs text-red-700 underline"
                    onClick={() => onChange(bindings.filter((_, i) => i !== position))}
                  >
                    Remove
                  </button>
                )}
              </div>

              {setId !== undefined && attributes.length > 0 && (
                <div>
                  <p className="mb-1 text-xs text-slate-600">
                    Only some of {binding.set} (optional)
                  </p>
                  <ExpressionBuilder
                    catalogue={buildFieldCatalogue({
                      entityTypes: [
                        {
                          id: setId,
                          name: binding.set,
                          attributes: attributes.map((a, index) => ({
                            id: index,
                            entity_type_id: setId,
                            name: a.name,
                            data_type: a.data_type,
                            required: false,
                            unit: null,
                            enum_values: null,
                            default_value: null,
                          })),
                        } as never,
                      ],
                      columns: [],
                    })}
                    value={fromIrWhere(binding.where, setId)}
                    onChange={(document) => {
                      const converted = toIrWhere(document);
                      replace(position, {
                        ...binding,
                        where: converted.ok ? converted.where : binding.where,
                        ...(converted.ok ? {} : { problems: converted.problems }),
                      } as Binding);
                    }}
                  />
                  {(binding as Binding & { problems?: string[] }).problems?.map((problem) => (
                    <p key={problem} role="alert" className="mt-1 text-xs text-red-600">
                      {problem}
                    </p>
                  ))}
                </div>
              )}
            </div>
          );

          function replace(at: number, next: Binding) {
            onChange(bindings.map((b, i) => (i === at ? next : b)));
          }
        })}
        <button
          type="button"
          className="rounded px-2 py-1 text-xs text-blue-700 underline"
          onClick={() =>
            onChange([
              ...bindings,
              { index: freeIndexName([...outer, ...bindings]), set: context.sets[0] ?? "" },
            ])
          }
        >
          Add an index
        </button>
      </div>
    </fieldset>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  emptyLabel,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  emptyLabel?: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <select
        id={id}
        className={`${INPUT_CLASS} w-auto text-xs`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.length === 0 && <option value="">{emptyLabel ?? "nothing to choose"}</option>}
        {value === "" && options.length > 0 && <option value="">choose…</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <input
        id={id}
        className={`${INPUT_CLASS} w-24 text-xs`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      {/* Not `type="number"`: an invalid entry reports as "" there, which is
          indistinguishable from empty (Task 11's finding). */}
      <input
        id={id}
        inputMode="numeric"
        className={`${INPUT_CLASS} w-24 text-xs`}
        value={String(value)}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (/^[+-]?\d*$/.test(event.target.value) && Number.isSafeInteger(next)) onChange(next);
        }}
      />
    </div>
  );
}
