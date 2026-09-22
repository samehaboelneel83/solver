import { useId, type ReactNode } from "react";
import ExpressionBuilder from "../expressions/ExpressionBuilder";
import { buildFieldCatalogue } from "../expressions";
import { INPUT_CLASS } from "../components/attrTypes";
import { TERM_KINDS, isName } from "../ir/contract";
import type { TermKind, TraversalDepth } from "../ir";
import {
  boundIndices,
  cleanBinding,
  describeTerm,
  emptyTerm,
  freeIndexName,
  uniqueByIndex,
  nextBinding,
  isGeneratedIndex,
  seedForSet,
  arithmeticAttributes,
  mentionsVariable,
  TERM_LABELS,
  termKind,
  viaOf,
  walkKey,
  walksAvailable,
  type Binding,
  type ModelContext,
  type Term,
} from "./terms";
import { fromIrWhere, toIrWhere } from "./whereFilter";
import { TreeItem, TreeView } from "../components/ui/tree-view";

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
  /** Hover actions on the tree row (remove a summand, etc.). */
  actions?: ReactNode;
};

export default function TermBuilder({
  value,
  onChange,
  context,
  bound,
  depth = 0,
  label,
  actions,
}: TermBuilderProps) {
  const kindId = useId();
  const kind = termKind(value);
  const nested = kind === "sum" || kind === "add" || kind === "mul";
  const namedBlock = Boolean(label);
  // A sum needs a set to range over. Offering one with none declared would
  // mint a binding whose set is empty — refused on publish.
  const offeredKinds =
    context.sets.length > 0 || kind === "sum"
      ? TERM_KINDS
      : TERM_KINDS.filter((option) => option !== "sum");
  const name = label ?? TERM_LABELS[kind];
  const kindSelect = (
    <>
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
        {offeredKinds.map((option) => (
          <option key={option} value={option}>
            {TERM_LABELS[option]}
          </option>
        ))}
      </select>
    </>
  );

  return (
    <TreeItem
      name={name}
      leaf={!nested && !namedBlock}
      actions={actions}
      header={
        namedBlock ? (
          <>
            <span className="text-xs font-medium text-slate-600">{label}</span>
            <span className="font-mono text-xs text-slate-500">{describeTerm(value)}</span>
          </>
        ) : (
          <>
            {kindSelect}
            <span className="font-mono text-xs text-slate-500">{describeTerm(value)}</span>
          </>
        )
      }
    >
      {namedBlock && <div className="mb-2 flex flex-wrap items-center gap-2">{kindSelect}</div>}
      <Body value={value} onChange={onChange} context={context} bound={bound} depth={depth} />
    </TreeItem>
  );
}

function Body({
  value,
  onChange,
  context,
  bound,
  depth,
}: Required<Omit<TermBuilderProps, "label" | "actions">>) {
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
            options={uniqueByIndex(bound.filter((b) => b.set === set)).map((b) => ({
              value: b.index,
              label: `${b.index} in ${b.set}`,
            }))}
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
    const attributes = binding ? arithmeticAttributes(context, binding.set) : [];
    return (
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label="Of"
          value={term.attr.of}
          options={uniqueByIndex(bound).map((b) => ({
            value: b.index,
            label: `${b.index} in ${b.set}`,
          }))}
          emptyLabel="nothing is bound here"
          onChange={(next) => onChange({ attr: { of: next, name: "" } })}
        />
        <Select
          label="Attribute"
          value={term.attr.name}
          options={attributes.map((a) => ({ value: a.name, label: a.name }))}
          emptyLabel={binding ? `${binding.set} has no numeric attribute` : "choose an index first"}
          onChange={(next) => onChange({ attr: { of: term.attr.of, name: next } })}
        />
        {binding && attributes.length === 0 && (
          <p className="text-xs text-slate-500">
            Arithmetic reads numeric attributes, so text, dates and times cannot appear here.
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
          <TermBuilder
            key={position}
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
            actions={
              term.add.length > 2 ? (
                <button
                  type="button"
                  className="rounded px-2 py-1 text-xs text-red-700 underline"
                  onClick={() => onChange({ add: term.add.filter((_, i) => i !== position) })}
                >
                  Remove
                </button>
              ) : undefined
            }
          />
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
  /** A `forall` may be omitted entirely; a sum's `over` may not. */
  minBindings?: number;
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
export function BindingsEditor({
  bindings,
  onChange,
  context,
  outer,
  legend,
  minBindings = 1,
}: BindingsEditorProps) {
  return (
    <TreeItem
      name={legend}
      header={<span className="text-xs font-medium text-slate-600">{legend}</span>}
    >
      <TreeView>
        {bindings.map((binding, position) => {
          const setId = context.setIds[binding.set];
          const attributes = context.attributes[binding.set] ?? [];
          const hasFilter = setId !== undefined && attributes.length > 0;
          const overName = `Over ${binding.index} in ${binding.set}`;
          return (
            <TreeItem
              key={position}
              name={overName}
              header={
                <>
                  <span className="text-xs font-medium text-slate-600">Over</span>
                  <span className="font-mono text-xs text-slate-500">
                    {binding.index} in {binding.set}
                  </span>
                </>
              }
              actions={
                bindings.length > minBindings ? (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-xs text-red-700 underline"
                    aria-label={`Remove ${binding.index} in ${binding.set}`}
                    onClick={() => onChange(bindings.filter((_, i) => i !== position))}
                  >
                    Remove
                  </button>
                ) : undefined
              }
            >
              <div className="flex flex-wrap items-end gap-2 py-1">
                <TextField
                  label="Index"
                  value={binding.index}
                  problem={indexProblem(binding.index, [
                    ...outer,
                    ...bindings.filter((_, i) => i !== position),
                  ])}
                  onChange={(next) => replace(position, { ...binding, index: next })}
                />
                <Select
                  label="Set"
                  value={binding.set}
                  options={context.sets.map((s) => ({ value: s, label: s }))}
                  onChange={(next) => {
                    const others = [...outer, ...bindings.filter((_, i) => i !== position)];
                    const { via: _dropped, where: _cleared, problems: _ui, ...rest } = binding as Binding & {
                      problems?: string[];
                    };
                    replace(
                      position,
                      cleanBinding({
                        ...rest,
                        set: next,
                        index: isGeneratedIndex(binding.index, binding.set)
                          ? freeIndexName(others, seedForSet(next))
                          : binding.index,
                      })
                    );
                  }}
                />
                <WalkPicker
                  binding={binding}
                  context={context}
                  // Only what is bound FURTHER OUT, and the bindings before
                  // this one -- the contract requires the anchor to be bound
                  // where the traversal starts, so a later sibling is not a
                  // candidate. Offering one would build a document the
                  // validator refuses.
                  earlier={[...outer, ...bindings.slice(0, position)]}
                  onChange={(next) => replace(position, next)}
                />
              </div>
              {hasFilter ? (
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
                    label={`Filter for ${binding.index} in ${binding.set}`}
                    value={fromIrWhere(binding.where, setId)}
                    onChange={(document) => {
                      const converted = toIrWhere(document);
                      if (!converted.ok) {
                        // Keep the last good where; surface the reason inline.
                        // `problems` is UI-only — cleanBinding strips it on publish.
                        replace(position, {
                          ...binding,
                          problems: converted.problems,
                        } as Binding & { problems?: string[] });
                        return;
                      }
                      replace(
                        position,
                        cleanBinding({
                          ...binding,
                          where: converted.where,
                        })
                      );
                    }}
                  />
                  {(binding as Binding & { problems?: string[] }).problems?.map((problem) => (
                    <p key={problem} role="alert" className="mt-1 text-xs text-red-600">
                      {problem}
                    </p>
                  ))}
                </div>
              ) : null}
            </TreeItem>
          );

          function replace(at: number, next: Binding) {
            onChange(bindings.map((b, i) => (i === at ? next : b)));
          }
        })}
        {context.sets.length > 0 && (
          <button
            type="button"
            className="rounded px-2 py-1 text-xs text-blue-700 underline"
            onClick={() => onChange([...bindings, nextBinding([...outer, ...bindings], context)])}
          >
            Add an index
          </button>
        )}
      </TreeView>
    </TreeItem>
  );
}

/** Why this index name cannot stand, or null when it is fine. */
function indexProblem(index: string, taken: Binding[]): string | null {
  if (!index) return "An index needs a name.";
  if (!isName(index)) {
    return "A name starts with a letter and uses lower-case letters, digits and underscores.";
  }
  if (taken.some((binding) => binding.index === index)) {
    return `The index '${index}' is already bound here.`;
  }
  return null;
}

/**
 * The relationship picker: "only the ones reached through …".
 *
 * It offers nothing at all unless a walk is possible — the model has to
 * declare a relationship type with an end of this binding's set, and an
 * index at the other end has to be bound already. Both conditions are the
 * contract's (`binding_via_endpoint_mismatch`, `binding_via_anchor_not_bound`),
 * so a refusal for either is unreachable from here rather than merely
 * unlikely.
 *
 * Depth appears only on a self-joining type, because walking twice along a
 * relationship whose ends differ lands nowhere and the contract refuses it.
 */
/** Not `""`: `Select` reads the empty string as "nothing chosen yet" and
 * prepends a "choose…" option. Ranging over the whole set is a choice, and
 * the default one. */
const NO_WALK = "all";

function WalkPicker({
  binding,
  context,
  earlier,
  onChange,
}: {
  binding: Binding;
  context: ModelContext;
  earlier: Binding[];
  onChange: (binding: Binding) => void;
}) {
  const offers = walksAvailable(context, binding.set, earlier);
  if (offers.length === 0) return null;

  const current = viaOf(binding);
  const offer = current
    ? offers.find((o) => o.rel === current.rel && o.anchorEnd === current.anchorEnd)
    : undefined;

  function choose(key: string) {
    if (key === NO_WALK) {
      const { via: _dropped, ...rest } = binding;
      onChange(rest);
      return;
    }
    const picked = offers.find((o) => walkKey(o.rel, o.anchorEnd) === key);
    if (!picked) return;
    onChange({
      ...binding,
      via: { rel: picked.rel, [picked.anchorEnd]: picked.anchors[0] } as Binding["via"],
    });
  }

  function anchor(index: string) {
    if (!current) return;
    onChange({ ...binding, via: { rel: current.rel, [current.anchorEnd]: index, ...depthPart() } });
  }

  function depthPart() {
    const depth = binding.via?.depth;
    return depth ? { depth } : {};
  }

  return (
    <>
      <Select
        label="Reached through"
        value={current ? walkKey(current.rel, current.anchorEnd) : NO_WALK}
        options={[
          { value: NO_WALK, label: "all of them" },
          ...offers.map((o) => ({
            value: walkKey(o.rel, o.anchorEnd),
            // A hierarchy is one_to_many from parent to child, so the
            // from-end is down the tree and the to-end is up. A walk
            // whose ends differ has only one offer, so the name is
            // enough — "along"/"against" was a direction the document
            // does not store.
            label: o.loops
              ? `${o.rel} ${o.anchorEnd === "from" ? "down the tree" : "up the tree"}`
              : o.rel,
          })),
        ]}
        onChange={choose}
      />
      {current && offer && offer.anchors.length > 1 && (
        <Select
          label="Starting at"
          value={current.anchor}
          options={offer.anchors.map((a) => ({
            value: a,
            label: (() => {
              const set = earlier.find((b) => b.index === a)?.set;
              return set ? `${a} in ${set}` : a;
            })(),
          }))}
          onChange={anchor}
        />
      )}
      {current && offer?.loops && (
        <Select
          label="How far"
          value={binding.via?.depth ?? "one"}
          options={[
            { value: "one", label: "the next hop only" },
            { value: "any", label: "everything under it" },
            { value: "any_or_self", label: "itself and everything under it" },
          ]}
          onChange={(depth) =>
            onChange({
              ...binding,
              via: {
                rel: current.rel,
                [current.anchorEnd]: current.anchor,
                ...(depth === "one" ? {} : { depth: depth as TraversalDepth }),
              },
            })
          }
        />
      )}
    </>
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
  problem,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  problem?: string | null;
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
        aria-invalid={problem ? "true" : undefined}
        aria-describedby={problem ? `${id}-problem` : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {problem && (
        <p id={`${id}-problem`} role="alert" className="mt-1 text-xs text-red-600">
          {problem}
        </p>
      )}
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
