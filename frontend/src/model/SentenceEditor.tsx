/**
 * The Sentence view, editable: a rule or goal read in plain words, with every
 * word that can change being a blank to fill in -- a number, which decision
 * or data, which item, which set, “at most / exactly / at least”.
 *
 *   For every [day ▾] [d], the total of [assign ▾] of [e ▾], [d ▾], over every
 *   [employee ▾] [e], must be [at least ▾] [demand ▾] of [d ▾].
 *
 * The words around the blanks come from the same reading as `ruleSentence`.
 * Changing the shape (adding a term, wrapping a part in a total) is done in
 * the Boxes view, one click away; a blank only changes a leaf.
 */
import { useEffect, useState, type ReactNode } from "react";
import { FUNCTIONS } from "../ir";
import { cellText } from "../lib/irBlocks/catalogue";
import { fillIndices, withWhere, type Binding, type Constraint, type ModelContext, type Term } from "./terms";
import { AttrBlanks, WalkBlanks } from "./WalkBlanks";
import { WhereBlanks } from "./WhereBlanks";

const BLANK = "mx-0.5 inline-block rounded border border-slate-300 bg-white px-1 py-0 align-baseline text-sm text-slate-900";

function NumberBlank({ value, label, onChange }: { value: number; label: string; onChange: (next: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <input aria-label={label} inputMode="decimal" className={`${BLANK} w-16 font-mono`} value={text}
      onChange={(event) => {
        setText(event.target.value);
        const next = Number(event.target.value);
        if (event.target.value.trim() !== "" && Number.isFinite(next)) onChange(next);
      }} />
  );
}

function Choice({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (next: string) => void;
}) {
  return (
    <select aria-label={label} className={BLANK} value={value} onChange={(event) => onChange(event.target.value)}>
      {!options.some(([v]) => v === value) && <option value={value}>{value || "choose…"}</option>}
      {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
    </select>
  );
}

/** "every [employee ▾] [e]", for each binding, joined with "and". */
export function BindingBlanks({ label, bindings, bound = [], context, onChange }: {
  label: string;
  bindings: Binding[];
  /** What is bound around these bindings: where a walk can start. */
  bound?: Binding[];
  context: ModelContext;
  onChange: (next: Binding[]) => void;
}) {
  return (
    <>
      {bindings.map((binding, i) => (
        <span key={i}>
          {i > 0 && " and "}every
          <Choice label={`${label}: set ${i + 1}`} value={binding.set} options={context.sets.map((s) => [s, s])}
            onChange={(set) => onChange(bindings.map((b, j) => (j === i ? { index: b.index, set } : b)))} />
          <input aria-label={`${label}: name ${i + 1}`} className={`${BLANK} w-10 font-mono`} value={binding.index}
            onChange={(event) => onChange(bindings.map((b, j) => (j === i ? { ...b, index: event.target.value.trim() } : b)))} />
          <WhereBlanks label={`${label}: set ${i + 1}`} set={binding.set} where={binding.where} context={context} className={BLANK}
            onChange={(where) => onChange(bindings.map((b, j) => (j === i ? withWhere(b, where) : b)))} />
          <WalkBlanks label={`${label}: set ${i + 1}`} binding={binding} earlier={[...bound, ...bindings.slice(0, i)]} context={context} className={BLANK}
            onChange={(next) => onChange(bindings.map((b, j) => (j === i ? next : b)))} />
        </span>
      ))}
    </>
  );
}

function negated(term: Term): Term | null {
  if ("mul" in term && "const" in term.mul[0] && term.mul[0].const === -1) return term.mul[1];
  return null;
}

/** One term as words and blanks. `path` names it the way the checker and the boxes do. */
export function TermWords({ term, path, context, bound, onChange, grouped = false }: {
  term: Term;
  path: string;
  context: ModelContext;
  bound: Binding[];
  onChange: (next: Term) => void;
  grouped?: boolean;
}): ReactNode {
  const label = (what: string) => `${path}: ${what}`;
  const at = (step: string) => (path ? `${path} › ${step}` : step);
  const words = (part: Term, step: string, set: (next: Term) => void, inner = bound, group = false) => (
    <TermWords key={step} term={part} path={at(step)} context={context} bound={inner} onChange={set} grouped={group} />
  );

  if ("const" in term) return <NumberBlank value={term.const} label={label("number")} onChange={(value) => onChange({ const: value })} />;
  if ("var" in term || "par" in term) {
    const isVar = "var" in term;
    const name = isVar ? term.var : term.par;
    const table = isVar ? context.variables : context.parameters;
    const names = Object.keys(table).filter((n) => !isVar || context.variables[n].domain !== "interval");
    const sets = table[name]?.index ?? [];
    return (
      <span>
        <Choice label={label(isVar ? "decision" : "data")} value={name} options={names.map((n) => [n, n])}
          onChange={(next) => {
            const wanted = table[next]?.index ?? [];
            const index = fillIndices(wanted.length, wanted, bound);
            onChange(isVar ? { var: next, index } : { par: next, index });
          }} />
        {term.index.length > 0 && " of "}
        {term.index.map((cell, i) => (
          <span key={i}>
            {i > 0 && ", "}
            {typeof cell === "string" ? (
              <Choice label={label(`which ${sets[i] ?? "item"}`)} value={cell} options={bound.map((b) => [b.index, b.index])}
                onChange={(next) => {
                  const index = term.index.map((c, j) => (j === i ? next : c));
                  onChange(isVar ? { var: name, index } : { par: name, index });
                }} />
            ) : <span className="font-mono">{cellText(cell)}</span>}
          </span>
        ))}
      </span>
    );
  }
  if ("attr" in term) {
    return <AttrBlanks label={label} term={term} bound={bound} context={context} className={BLANK} onChange={onChange} />;
  }
  if ("sum" in term) {
    return (
      <span>
        the total of {words(term.sum, "what is totalled", (sum) => onChange({ ...term, sum }), [...bound, ...term.over])}, over{" "}
        <BindingBlanks label={label("runs over")} bindings={term.over} bound={bound} context={context} onChange={(over) => onChange({ ...term, over })} />
      </span>
    );
  }
  if ("add" in term) {
    const body = term.add.map((part, i) => {
      const minus = negated(part);
      const step = `term ${i + 1}`;
      return (
        <span key={step}>
          {i > 0 && (minus ? " minus " : " plus ")}
          {i === 0 && minus && "minus "}
          {minus
            ? words(minus, step, (next) => onChange({ add: term.add.map((p, j) => (j === i ? { mul: [{ const: -1 }, next] } : p)) }))
            : words(part, step, (next) => onChange({ add: term.add.map((p, j) => (j === i ? next : p)) }))}
        </span>
      );
    });
    return grouped ? <span>({body})</span> : <span>{body}</span>;
  }
  if ("mul" in term) {
    const minus = negated(term);
    if (minus) return <span>minus {words(minus, "factor 2", (next) => onChange({ mul: [{ const: -1 }, next] }))}</span>;
    return (
      <span>
        {words(term.mul[0], "factor 1", (next) => onChange({ mul: [next, term.mul[1]] }), bound, true)} times{" "}
        {words(term.mul[1], "factor 2", (next) => onChange({ mul: [term.mul[0], next] }), bound, true)}
      </span>
    );
  }
  if ("fn" in term) {
    return (
      <span>
        <Choice label={label("function")} value={term.fn} options={Object.entries(FUNCTIONS).map(([n, spec]) => [n, spec.text])}
          onChange={(fn) => onChange({ ...term, fn })} />
        {" of "}
        {words(term.of, `${term.fn} of`, (of) => onChange({ ...term, of }))}
      </span>
    );
  }
  if ("predict" in term) {
    const names = Object.keys(context.predictors ?? {});
    return (
      <span>
        what{" "}
        <Choice label={label("trained model")} value={term.predict} options={names.map((n) => [n, n])}
          onChange={(predict) => {
            const inputs = context.predictors?.[predict]?.inputs ?? term.of.length;
            onChange({ predict, of: Array.from({ length: inputs }, (_, i) => term.of[i] ?? { const: 0 }) });
          }} />
        {" predicts from "}
        {term.of.map((input, i) => (
          <span key={i}>
            {i > 0 && " and "}
            {words(input, `input ${i + 1}`, (next) => onChange({ ...term, of: term.of.map((p, j) => (j === i ? next : p)) }))}
          </span>
        ))}
      </span>
    );
  }
  return <span>a curve of {term.pwl.var} through {term.points.length} points</span>;
}

const RELATIONS: [string, string][] = [["<=", "must be at most"], ["=", "must be exactly"], [">=", "must be at least"]];

/** A rule's sentence with its blanks. */
export function RuleWords({ rule, context, onChange }: { rule: Constraint; context: ModelContext; onChange: (next: Constraint) => void }) {
  if (rule.left == null || rule.right == null) return <span>This rule does not say anything yet.</span>;
  const forall = rule.forall ?? [];
  return (
    <span>
      {forall.length > 0 && (
        <>
          For{" "}
          <BindingBlanks label="for each" bindings={forall} context={context}
            onChange={(next) => onChange({ ...rule, forall: next.length ? next : undefined })} />
          ,{" "}
        </>
      )}
      <TermWords term={rule.left} path="left side" context={context} bound={forall} onChange={(left) => onChange({ ...rule, left })} />
      {"sum" in rule.left ? ", " : " "}
      <Choice label="comparison" value={rule.relation ?? "<="} options={RELATIONS}
        onChange={(relation) => onChange({ ...rule, relation: relation as Constraint["relation"] })} />{" "}
      <TermWords term={rule.right} path="right side" context={context} bound={forall} onChange={(right) => onChange({ ...rule, right })} />
      {rule.when?.var ? `, only while ${rule.when.var} is ${rule.when.is === 0 ? "no" : "yes"}` : ""}.
      {rule.severity === "soft" ? ` It is preferred, not required (weight ${rule.weight ?? 1}).` : ""}
    </span>
  );
}
