/**
 * An equation as a drill-down diagram: nested boxes, each opening with ▶/▼ to
 * show its parts side by side, joined by lines -- and each part opening in
 * turn, down to numbers and names. The same IR the equation line edits; any
 * box can be edited on its own, as an equation for just that part, with the
 * indices bound around it in scope.
 *
 * Every box hands its children a "replace me" callback, so an edit deep in
 * the tree rebuilds only the path above it.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Pencil } from "lucide-react";
import EquationField, { chipsFor } from "./EquationField";
import { parseBindings, parseTermIn, printBinding, printTerm } from "./formula";
import { cellText } from "../lib/irBlocks/catalogue";
import type { Binding, Constraint, ModelContext, Term } from "./terms";

/** "Open all" / "Close all": a request every box follows once. */
type OpenAll = { open: boolean; seq: number } | null;
const OpenAllContext = createContext<OpenAll>(null);

function kindOf(term: Term): string {
  if ("const" in term) return "number";
  if ("var" in term) return "variable";
  if ("par" in term) return "parameter";
  if ("attr" in term) return "attribute";
  if ("sum" in term) return "sum";
  if ("add" in term) return "added together";
  if ("mul" in term) return "product";
  if ("fn" in term) return `function ${term.fn}`;
  if ("predict" in term) return `prediction of ${term.predict}`;
  return "curve";
}

const BOX = "rounded-md border border-dotted border-slate-400 bg-white";
const HEADER = "flex min-w-0 items-center gap-2 rounded-t-md bg-blue-50/60 px-2 py-1";
const ICON_BUTTON =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-600 hover:bg-slate-100 hover:text-slate-900";

/** Parts side by side under their parent, each hanging from a joining line. */
export function Children({ children }: { children: ReactNode[] }) {
  return (
    <div className="relative mt-2 flex flex-wrap items-start gap-3 border-t border-slate-300 px-2 pb-2 pt-3">
      {children.map((child, i) => (
        <div key={i} className="relative shrink-0 before:absolute before:-top-3 before:left-4 before:h-3 before:border-l before:border-slate-300 before:content-['']">
          {child}
        </div>
      ))}
    </div>
  );
}

/** A symbol between parts: the relation, `+`, `×`. */
function Joiner({ text }: { text: string }) {
  return <span className="mt-1 inline-block rounded bg-slate-100 px-2 py-1 font-mono text-sm font-semibold text-slate-800">{text}</span>;
}

function useOpen(initial: boolean): [boolean, (next: boolean) => void] {
  const [open, setOpen] = useState(initial);
  const all = useContext(OpenAllContext);
  useEffect(() => {
    if (all) setOpen(all.open);
  }, [all]);
  return [open, setOpen];
}

/** A box's header: the toggle, what it is, its text, and ✎. */
function Header({ label, kind, text, open, setOpen, openable, onEdit }: {
  label: string;
  kind: string;
  text: string;
  open: boolean;
  setOpen: (next: boolean) => void;
  openable: boolean;
  onEdit: () => void;
}) {
  return (
    <div className={HEADER}>
      {openable ? (
        <button type="button" aria-expanded={open} aria-label={`${open ? "Close" : "Open"} ${label}`} onClick={() => setOpen(!open)} className={ICON_BUTTON}>
          <span aria-hidden="true">{open ? "▼" : "▶"}</span>
        </button>
      ) : (
        <span className="inline-block w-7 shrink-0" aria-hidden="true" />
      )}
      <span className="shrink-0 text-xs font-semibold text-slate-700">{label}</span>
      <span className="shrink-0 rounded bg-slate-100 px-1.5 text-xs text-slate-600">{kind}</span>
      <code className="min-w-0 truncate font-mono text-xs text-slate-800" title={text}>{text}</code>
      <button type="button" aria-label={`Edit ${label}`} title="Edit this part" onClick={onEdit} className={`${ICON_BUTTON} ml-auto`}>
        <Pencil size={13} aria-hidden="true" />
      </button>
    </div>
  );
}

function Editing<T>({ label, text, parse, onCommit, onClose, context }: {
  label: string;
  text: string;
  parse: (text: string) => ReturnType<typeof parseTermIn> | ReturnType<typeof parseBindings>;
  onCommit: (value: T) => void;
  onClose: () => void;
  context: ModelContext;
}) {
  return (
    <div className="flex items-start gap-2 p-2">
      <EquationField
        label={`Equation for ${label}`}
        equation={text}
        parse={parse as (text: string) => { ok: true; value: T } | { ok: false; message: string; at: number; end: number }}
        onCommit={(value) => {
          onCommit(value);
          onClose();
        }}
        chips={chipsFor(context)}
        sets={context.sets}
      />
      <button type="button" onClick={onClose} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700">
        Done
      </button>
    </div>
  );
}

/** What a sum or a rule ranges over. */
function BindingsBox({ label, bindings, bound, context, onChange }: {
  label: string;
  bindings: Binding[];
  bound: Binding[];
  context: ModelContext;
  onChange: (next: Binding[]) => void;
}) {
  const [open, setOpen] = useOpen(false);
  const [editing, setEditing] = useState(false);
  const text = bindings.map(printBinding).join(", ");
  return (
    <div className={`${BOX} min-w-[12rem]`}>
      {editing ? (
        <Editing<Binding[]> label={label} text={text} context={context} onClose={() => setEditing(false)}
          parse={(t) => parseBindings(t, context, bound)} onCommit={onChange} />
      ) : (
        <Header label={label} kind="ranges over" text={text} open={open} setOpen={setOpen} openable onEdit={() => setEditing(true)} />
      )}
      {open && !editing && (
        <ul className="space-y-1 px-3 py-2 text-xs">
          {bindings.map((binding) => (
            <li key={binding.index} className="font-mono text-slate-800">
              {binding.index} <span className="text-slate-500">in</span> {binding.set}
              {binding.where?.map((filter, i) => (
                <span key={i} className="block pl-4 text-slate-600">
                  {i === 0 ? "where" : "and"} {filter.attr} {filter.op === "notIn" ? "not in" : filter.op} {typeof filter.value === "object" && filter.value !== null && !Array.isArray(filter.value) ? cellText(filter.value) : JSON.stringify(filter.value)}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One part of an equation, opening to its own parts, recursively. */
export function PartBox({ label, term, bound, context, onChange, startOpen = false }: {
  label: string;
  term: Term;
  bound: Binding[];
  context: ModelContext;
  onChange: (next: Term) => void;
  startOpen?: boolean;
}) {
  const [open, setOpen] = useOpen(startOpen);
  const [editing, setEditing] = useState(false);
  const text = printTerm(term);
  const openable = !("const" in term) && !("attr" in term) && !("pwl" in term)
    && !(("var" in term || "par" in term) && term.index.length === 0);

  let parts: ReactNode[] = [];
  if (open) {
    if ("sum" in term) {
      parts = [
        <BindingsBox key="over" label="over" bindings={term.over} bound={bound} context={context} onChange={(over) => onChange({ ...term, over })} />,
        <PartBox key="of" label="of" term={term.sum} bound={[...bound, ...term.over]} context={context} onChange={(sum) => onChange({ ...term, sum })} />,
      ];
    } else if ("add" in term) {
      term.add.forEach((part, i) => {
        if (i > 0) parts.push(<Joiner key={`op${i}`} text="+" />);
        parts.push(
          <PartBox key={i} label={`term ${i + 1}`} term={part} bound={bound} context={context}
            onChange={(next) => onChange({ add: term.add.map((p, j) => (j === i ? next : p)) })} />,
        );
      });
    } else if ("mul" in term) {
      parts = [
        <PartBox key="l" label="factor 1" term={term.mul[0]} bound={bound} context={context} onChange={(next) => onChange({ mul: [next, term.mul[1]] })} />,
        <Joiner key="x" text="×" />,
        <PartBox key="r" label="factor 2" term={term.mul[1]} bound={bound} context={context} onChange={(next) => onChange({ mul: [term.mul[0], next] })} />,
      ];
    } else if ("fn" in term) {
      parts = [<PartBox key="of" label={`${term.fn} of`} term={term.of} bound={bound} context={context} onChange={(of) => onChange({ ...term, of })} />];
    } else if ("predict" in term) {
      parts = term.of.map((input, i) => (
        <PartBox key={i} label={`input ${i + 1}`} term={input} bound={bound} context={context}
          onChange={(next) => onChange({ ...term, of: term.of.map((p, j) => (j === i ? next : p)) })} />
      ));
    } else if ("var" in term || "par" in term) {
      const name = "var" in term ? term.var : term.par;
      const sets = ("var" in term ? context.variables[name]?.index : context.parameters[name]?.index) ?? [];
      parts = term.index.map((cell, i) => (
        <span key={i} className="inline-block rounded border border-dotted border-slate-400 px-2 py-1 font-mono text-xs text-slate-800">
          {cellText(cell)}
          {sets[i] && <span className="ml-1 text-slate-500">({sets[i]})</span>}
        </span>
      ));
    }
  }

  return (
    <div className={`${BOX} min-w-[10rem]`} data-testid="equation-part">
      {editing ? (
        <Editing<Term> label={label} text={text} context={context} onClose={() => setEditing(false)}
          parse={(t) => parseTermIn(t, context, bound)} onCommit={onChange} />
      ) : (
        <Header label={label} kind={kindOf(term)} text={text} open={open} setOpen={setOpen} openable={openable} onEdit={() => setEditing(true)} />
      )}
      {open && !editing && parts.length > 0 && <Children>{parts}</Children>}
    </div>
  );
}

/** "Open all" / "Close all" for one diagram. */
function OpenAllControls({ onOpen }: { onOpen: (open: boolean) => void }) {
  return (
    <div className="flex gap-2 text-xs">
      <button type="button" className="rounded py-1 text-blue-700 underline" onClick={() => onOpen(true)}>Open all</button>
      <button type="button" className="rounded py-1 text-blue-700 underline" onClick={() => onOpen(false)}>Close all</button>
    </div>
  );
}

/** A rule as a diagram: what it ranges over, its two sides and their relation. */
export function RuleDiagram({ rule, context, onChange }: {
  rule: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const [all, setAll] = useState<OpenAll>(null);
  const forall = rule.forall ?? [];
  if (!rule.left || !rule.right) return null;
  return (
    <OpenAllContext.Provider value={all}>
      <div className="space-y-1">
        <OpenAllControls onOpen={(open) => setAll((prev) => ({ open, seq: (prev?.seq ?? 0) + 1 }))} />
        <div className="overflow-x-auto rounded-md border border-dashed border-slate-400 p-2" data-testid="rule-diagram">
          <p className="px-1 pb-1 text-center font-mono text-sm font-semibold text-slate-900">
            {rule.id || "rule"} <span className="font-sans text-xs font-normal text-slate-500">({rule.severity === "soft" ? "preferred" : "required"})</span>
          </p>
          <Children>
            {[
              ...(forall.length
                ? [<BindingsBox key="forall" label="for each" bindings={forall} bound={[]} context={context}
                    onChange={(next) => onChange({ ...rule, forall: next })} />]
                : []),
              <PartBox key="left" label="left side" term={rule.left} bound={forall} context={context} onChange={(left) => onChange({ ...rule, left })} />,
              <Joiner key="rel" text={rule.relation ?? "?"} />,
              <PartBox key="right" label="right side" term={rule.right} bound={forall} context={context} onChange={(right) => onChange({ ...rule, right })} />,
            ]}
          </Children>
        </div>
      </div>
    </OpenAllContext.Provider>
  );
}

/** A goal's expression as a diagram. */
export function GoalDiagram({ label, expression, context, onChange }: {
  label: string;
  expression: Term;
  context: ModelContext;
  onChange: (next: Term) => void;
}) {
  const [all, setAll] = useState<OpenAll>(null);
  return (
    <OpenAllContext.Provider value={all}>
      <div className="space-y-1">
        <OpenAllControls onOpen={(open) => setAll((prev) => ({ open, seq: (prev?.seq ?? 0) + 1 }))} />
        <div className="overflow-x-auto rounded-md border border-dashed border-slate-400 p-2" data-testid="goal-diagram">
          <PartBox label={label} term={expression} bound={[]} context={context} onChange={onChange} startOpen />
        </div>
      </div>
    </OpenAllContext.Provider>
  );
}
