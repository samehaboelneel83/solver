/**
 * Boxes: a rule or goal as nested, typed blocks (docs/design/nested-blocks.md).
 *
 * Each box is one node of the IR's expression tree -- a decision, a piece of
 * data, a number, an operation, a total over a set, the comparison, the rule
 * -- coloured by what it is, and holding its parts inside it. Nothing here is
 * a drawing of the model: every box edits the IR node it shows, and the
 * choices it offers are only the ones that keep the tree well formed (a
 * number slot takes numbers; a comparison is “at most”, “exactly” or “at
 * least”; an index takes a name bound around it).
 *
 * Problems are checked per box (`blockCheck`): a box says what is wrong with
 * itself, and how many problems its parts hold, so the path to a problem deep
 * inside is visible from the top.
 */
import { useEffect, useState, type ReactNode } from "react";
import { FUNCTIONS } from "../ir";
import { cellText } from "../lib/irBlocks/catalogue";
import { checkGoal, checkRule, explain, problemsAt, type Problem } from "./blockCheck";
import { ruleSentence, termSentence } from "./ruleSentence";
import {
  arithmeticAttributes,
  describeWhen,
  emptyTerm,
  fillIndices,
  nextBinding,
  type Binding,
  type Constraint,
  type ModelContext,
  type Term,
} from "./terms";

type Role = "decision" | "data" | "number" | "operation" | "total" | "comparison" | "scope" | "rule";

/** One colour per kind of thing, the same in every box. */
const ROLE_STYLE: Record<Role, { box: string; tag: string }> = {
  decision: { box: "border-sky-300 bg-sky-50", tag: "bg-sky-100 text-sky-800" },
  data: { box: "border-emerald-300 bg-emerald-50", tag: "bg-emerald-100 text-emerald-800" },
  number: { box: "border-slate-300 bg-white", tag: "bg-slate-100 text-slate-700" },
  // Containers are drawn by their border only: fills that nest would stack up.
  operation: { box: "border-violet-300 bg-transparent", tag: "bg-violet-100 text-violet-800" },
  total: { box: "border-indigo-300 bg-transparent", tag: "bg-indigo-100 text-indigo-800" },
  comparison: { box: "border-amber-300 bg-transparent", tag: "bg-amber-100 text-amber-800" },
  scope: { box: "border-teal-300 bg-transparent", tag: "bg-teal-100 text-teal-800" },
  rule: { box: "border-slate-300 bg-white", tag: "bg-slate-100 text-slate-800" },
};

/** Controls sized to what they hold: a box is a line of words, not a form. */
const SELECT = "inline-block rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900";

function roleOf(term: Term): Role {
  if ("var" in term) return "decision";
  if ("par" in term || "attr" in term) return "data";
  if ("const" in term) return "number";
  if ("sum" in term) return "total";
  return "operation";
}

function titleOf(term: Term): string {
  if ("const" in term) return "Number";
  if ("var" in term) return "Decision";
  if ("par" in term) return "Data";
  if ("attr" in term) return "Data of an item";
  if ("sum" in term) return "Total";
  if ("add" in term) return "Add up";
  if ("mul" in term) return "Multiply";
  if ("fn" in term) return "Function";
  if ("predict" in term) return "Prediction";
  return "Curve";
}

/** A box: its kind, its own problems, a quiet count of the problems inside, and its parts. */
function Box({ role, title, label, problems, path, actions, children }: {
  role: Role;
  title: string;
  label: string;
  problems: Problem[];
  path: string[];
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const { own, inside } = problemsAt(problems, path);
  const style = ROLE_STYLE[role];
  return (
    <div
      role="group"
      aria-label={`${title}: ${label}`}
      data-testid="block"
      data-role={role}
      className={`min-w-0 rounded-lg border-2 p-2 ${own.length ? "border-rose-300" : style.box.split(" ")[0]} ${style.box.split(" ")[1]}`}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${style.tag}`}>{title}</span>
        <span className="text-xs text-slate-500">{label}</span>
        {own.length > 0 && <span className="text-xs font-semibold text-rose-700" aria-hidden="true">!</span>}
        {inside > 0 && (
          <span className="text-xs text-amber-800">
            {inside} {inside === 1 ? "problem" : "problems"} inside
          </span>
        )}
        <span className="ml-auto">{actions}</span>
      </div>
      {own.map((problem, i) => (
        <p key={i} className="mb-1 text-xs text-rose-700">{problem.message.charAt(0).toUpperCase() + problem.message.slice(1)}.</p>
      ))}
      {children}
    </div>
  );
}

function Joiner({ text }: { text: string }) {
  return <span className="self-center px-1 font-mono text-base font-semibold text-slate-700" aria-hidden="true">{text}</span>;
}

/** What a box can become, or be put inside: only numbers, since every slot here holds a number. */
function ChangeMenu({ label, term, context, bound, onChange, onRemove }: {
  label: string;
  term: Term;
  context: ModelContext;
  bound: Binding[];
  onChange: (next: Term) => void;
  onRemove?: () => void;
}) {
  const numeric = Object.values(context.variables).some((spec) => spec.domain !== "interval");
  const attrs = bound.some((binding) => arithmeticAttributes(context, binding.set).length > 0);
  const predictors = Object.keys(context.predictors ?? {});
  const replace: [string, string, boolean][] = [
    ["const", "a number", true],
    ["var", "a decision", numeric],
    ["par", "data", Object.keys(context.parameters).length > 0],
    ["attr", "data of an item", attrs],
    ["sum", "a total over a set", context.sets.length > 0],
    ["add", "adding things up", true],
    ["mul", "multiplying two things", true],
    ["fn", "a function (log, square root…)", true],
    ["predict", "a trained model's prediction", predictors.length > 0],
  ];
  return (
    <select
      aria-label={`Change ${label}`}
      className={`${SELECT} w-28 py-0.5 text-xs text-slate-600`}
      value=""
      onChange={(event) => {
        const choice = event.target.value;
        if (choice === "remove") return onRemove?.();
        if (choice === "wrap:add") return onChange({ add: [term, { const: 0 }] });
        if (choice === "wrap:mul") return onChange({ mul: [{ const: 1 }, term] });
        if (choice === "wrap:neg") return onChange({ mul: [{ const: -1 }, term] });
        if (choice === "wrap:sum") return onChange({ sum: term, over: [nextBinding(bound, context)] });
        if (choice === "predict") {
          const name = predictors[0];
          const inputs = context.predictors?.[name]?.inputs ?? 1;
          return onChange({ predict: name, of: Array.from({ length: inputs }, () => ({ const: 0 })) });
        }
        if (choice) onChange(emptyTerm(choice as Parameters<typeof emptyTerm>[0], context, bound));
      }}
    >
      <option value="">Change…</option>
      <optgroup label="Replace it with">
        {replace.filter(([, , ok]) => ok).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </optgroup>
      <optgroup label="Put it inside">
        <option value="wrap:add">… plus something</option>
        <option value="wrap:mul">… times something</option>
        <option value="wrap:neg">minus …</option>
        {context.sets.length > 0 && <option value="wrap:sum">a total of it over a set</option>}
      </optgroup>
      {onRemove && <option value="remove">Remove it</option>}
    </select>
  );
}

/** A number, kept as typed until it reads as one. */
function NumberInput({ value, label, onChange }: { value: number; label: string; onChange: (next: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <input
      aria-label={label}
      inputMode="decimal"
      className={`${SELECT} w-28 font-mono`}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const next = Number(event.target.value);
        if (event.target.value.trim() !== "" && Number.isFinite(next)) onChange(next);
      }}
    />
  );
}

/** Index cells: each a name bound around this box. */
function IndexCells({ owner, sets, cells, bound, onChange }: {
  owner: string;
  sets: string[];
  cells: unknown[];
  bound: Binding[];
  onChange: (next: string[]) => void;
}) {
  if (cells.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-sm text-slate-600">
      for
      {cells.map((cell, i) => typeof cell === "string" ? (
        <select key={i} aria-label={`${owner}: which ${sets[i] ?? "item"}`} className={SELECT} value={cell}
          onChange={(event) => onChange(cells.map((c, j) => (j === i ? event.target.value : c)) as string[])}>
          {!bound.some((b) => b.index === cell) && <option value={cell}>{cell || "choose…"}</option>}
          {bound.map((b) => <option key={b.index} value={b.index}>{b.index} ({b.set})</option>)}
        </select>
      ) : (
        <code key={i} className="font-mono text-xs">{cellText(cell)}</code>
      ))}
    </span>
  );
}

/** The sets a total, or a rule, runs over: "every [person] called [p]". */
function BindingsEditor({ label, bindings, bound, context, onChange, removable }: {
  label: string;
  bindings: Binding[];
  bound: Binding[];
  context: ModelContext;
  onChange: (next: Binding[]) => void;
  removable: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {bindings.map((binding, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1 text-sm text-slate-700">
          <span>every</span>
          <select aria-label={`${label}: set ${i + 1}`} className={SELECT} value={binding.set}
            onChange={(event) => onChange(bindings.map((b, j) => (j === i ? { ...b, set: event.target.value } : b)))}>
            {!context.sets.includes(binding.set) && <option value={binding.set}>{binding.set || "choose…"}</option>}
            {context.sets.map((set) => <option key={set} value={set}>{set}</option>)}
          </select>
          <span>called</span>
          <input aria-label={`${label}: name ${i + 1}`} className={`${SELECT} w-16 font-mono`} value={binding.index}
            onChange={(event) => onChange(bindings.map((b, j) => (j === i ? { ...b, index: event.target.value.trim() } : b)))} />
          {(binding.where?.length ?? 0) > 0 && (
            <span className="text-xs text-slate-500">
              where {binding.where!.map((f) => `${f.attr} ${f.op} ${typeof f.value === "object" ? JSON.stringify(f.value) : String(f.value)}`).join(" and ")}
            </span>
          )}
          {(removable || bindings.length > 1) && (
            <button type="button" className="text-xs text-rose-700 underline" aria-label={`Remove ${binding.index || "this set"} from ${label}`}
              onClick={() => onChange(bindings.filter((_, j) => j !== i))}>
              remove
            </button>
          )}
        </div>
      ))}
      {context.sets.length > 0 && (
        <button type="button" className="self-start text-xs text-blue-700 underline"
          onClick={() => onChange([...bindings, nextBinding([...bound, ...bindings], context)])}>
          + another set
        </button>
      )}
    </div>
  );
}

/** One node of the expression tree, and its parts inside it. */
export function TermBlock({ term, label, path, problems, context, bound, onChange, onRemove }: {
  term: Term;
  label: string;
  path: string[];
  problems: Problem[];
  context: ModelContext;
  bound: Binding[];
  onChange: (next: Term) => void;
  onRemove?: () => void;
}) {
  const at = (step: string) => [...path, step];
  const child = (part: Term, step: string, set: (next: Term) => void, inner = bound, remove?: () => void) => (
    <TermBlock key={step} term={part} label={step} path={at(step)} problems={problems} context={context}
      bound={inner} onChange={set} onRemove={remove} />
  );
  const actions = <ChangeMenu label={label} term={term} context={context} bound={bound} onChange={onChange} onRemove={onRemove} />;
  let body: ReactNode;

  if ("const" in term) {
    body = <NumberInput value={term.const} label={`${label}: number`} onChange={(value) => onChange({ const: value })} />;
  } else if ("var" in term || "par" in term) {
    const isVar = "var" in term;
    const name = isVar ? term.var : term.par;
    const table = isVar ? context.variables : context.parameters;
    const names = Object.keys(table).filter((n) => !isVar || context.variables[n].domain !== "interval");
    const sets = table[name]?.index ?? [];
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={`${label}: ${isVar ? "which decision" : "which data"}`} className={SELECT} value={name}
          onChange={(event) => {
            const next = event.target.value;
            const wanted = table[next]?.index ?? [];
            const index = fillIndices(wanted.length, wanted, bound);
            onChange(isVar ? { var: next, index } : { par: next, index });
          }}>
          {!names.includes(name) && <option value={name}>{name || "choose…"}</option>}
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <IndexCells owner={name || label} sets={sets} cells={term.index} bound={bound}
          onChange={(index) => onChange(isVar ? { var: name, index } : { par: name, index })} />
      </div>
    );
  } else if ("attr" in term) {
    const binding = bound.find((b) => b.index === term.attr.of);
    const attrs = binding ? arithmeticAttributes(context, binding.set) : [];
    body = term.attr.along ? (
      <code className="font-mono text-sm">{term.attr.along} of {term.attr.name} along {term.attr.of}</code>
    ) : (
      <div className="flex flex-wrap items-center gap-1 text-sm text-slate-700">
        <select aria-label={`${label}: which number`} className={SELECT} value={term.attr.name}
          onChange={(event) => onChange({ attr: { ...term.attr, name: event.target.value } })}>
          {!attrs.some((a) => a.name === term.attr.name) && <option value={term.attr.name}>{term.attr.name || "choose…"}</option>}
          {attrs.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <span>of</span>
        <select aria-label={`${label}: of which item`} className={SELECT} value={term.attr.of}
          onChange={(event) => onChange({ attr: { ...term.attr, of: event.target.value } })}>
          {!binding && <option value={term.attr.of}>{term.attr.of || "choose…"}</option>}
          {bound.map((b) => <option key={b.index} value={b.index}>{b.index} ({b.set})</option>)}
        </select>
      </div>
    );
  } else if ("add" in term) {
    body = (
      <div className="flex flex-wrap items-start gap-2">
        {term.add.map((part, i) => [
          i > 0 && <Joiner key={`plus${i}`} text="+" />,
          child(part, `term ${i + 1}`, (next) => onChange({ add: term.add.map((p, j) => (j === i ? next : p)) }), bound,
            term.add.length > 2 ? () => onChange({ add: term.add.filter((_, j) => j !== i) }) : undefined),
        ])}
        <button type="button" className="self-center rounded border border-dashed border-violet-300 px-2 py-1 text-xs text-violet-800"
          onClick={() => onChange({ add: [...term.add, { const: 0 }] })}>
          + add a term
        </button>
      </div>
    );
  } else if ("mul" in term) {
    body = (
      <div className="flex flex-wrap items-start gap-2">
        {child(term.mul[0], "factor 1", (next) => onChange({ mul: [next, term.mul[1]] }))}
        <Joiner text="×" />
        {child(term.mul[1], "factor 2", (next) => onChange({ mul: [term.mul[0], next] }))}
      </div>
    );
  } else if ("sum" in term) {
    body = (
      <div className="space-y-2">
        <BindingsEditor label={`${label}: runs over`} bindings={term.over} bound={bound} context={context}
          onChange={(over) => onChange({ ...term, over })} removable={false} />
        {child(term.sum, "what is totalled", (sum) => onChange({ ...term, sum }), [...bound, ...term.over])}
      </div>
    );
  } else if ("fn" in term) {
    body = (
      <div className="space-y-2">
        <select aria-label={`${label}: which function`} className={SELECT} value={term.fn}
          onChange={(event) => onChange({ ...term, fn: event.target.value })}>
          {Object.entries(FUNCTIONS).map(([name, spec]) => <option key={name} value={name}>{name}: {spec.text}</option>)}
        </select>
        {child(term.of, `${term.fn} of`, (of) => onChange({ ...term, of }))}
      </div>
    );
  } else if ("predict" in term) {
    const names = Object.keys(context.predictors ?? {});
    body = (
      <div className="space-y-2">
        <select aria-label={`${label}: which trained model`} className={SELECT} value={term.predict}
          onChange={(event) => {
            const inputs = context.predictors?.[event.target.value]?.inputs ?? term.of.length;
            onChange({ predict: event.target.value, of: Array.from({ length: inputs }, (_, i) => term.of[i] ?? { const: 0 }) });
          }}>
          {!names.includes(term.predict) && <option value={term.predict}>{term.predict || "choose…"}</option>}
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <div className="flex flex-wrap items-start gap-2">
          {term.of.map((input, i) => child(input, `input ${i + 1}`, (next) => onChange({ ...term, of: term.of.map((p, j) => (j === i ? next : p)) })))}
        </div>
      </div>
    );
  } else {
    body = (
      <p className="text-sm text-slate-700">
        A curve of <code className="font-mono">{term.pwl.var}</code> through {term.points.length} points. Change its points under “More options”.
      </p>
    );
  }

  return (
    <Box role={roleOf(term)} title={titleOf(term)} label={label} problems={problems} path={path} actions={actions}>
      {body}
    </Box>
  );
}

/** What a rule or goal has to fix, in plain words -- or that it reads cleanly. */
function Summary({ problems }: { problems: Problem[] }) {
  if (problems.length === 0) {
    return <p className="text-xs text-emerald-800" role="status">✓ Complete: every part checks out.</p>;
  }
  return (
    <div className="text-xs text-rose-700" role="status">
      <p className="font-semibold">{problems.length} {problems.length === 1 ? "thing" : "things"} to fix:</p>
      <ul className="ml-4 list-disc">
        {problems.map((problem, i) => <li key={i}>{explain(problem)}</li>)}
      </ul>
    </div>
  );
}

const RELATIONS: [string, string][] = [["<=", "is at most"], ["=", "is exactly"], [">=", "is at least"]];

/** A rule as boxes: what it runs over, and the comparison of its two sides. */
export function RuleBlocks({ rule, context, onChange }: {
  rule: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const problems = checkRule(rule, context);
  const forall = rule.forall ?? [];
  const condition = describeWhen(rule.when);
  if (rule.left == null || rule.right == null) return null;
  const left = rule.left;
  const right = rule.right;
  return (
    <div className="space-y-2" data-testid="rule-blocks">
      <Summary problems={problems} />
      <Box role="rule" title="Rule" label={rule.id || "this rule"} problems={problems} path={[]}>
        <div className="space-y-2">
          {forall.length > 0 ? (
            <Box role="scope" title="For each" label="the rule is checked once for" problems={problems} path={["for each"]}>
              <BindingsEditor label="For each" bindings={forall} bound={[]} context={context} removable
                onChange={(next) => onChange({ ...rule, forall: next.length ? next : undefined })} />
            </Box>
          ) : context.sets.length > 0 && (
            <button type="button" className="text-xs text-blue-700 underline"
              onClick={() => onChange({ ...rule, forall: [nextBinding([], context)] })}>
              + check it once for every item of a set
            </button>
          )}
          {condition && (
            <p className="rounded border border-teal-200 bg-teal-50 px-2 py-1 text-xs text-teal-800">
              Only {condition.replace(/^only /, "")}. Change the condition under “More options”.
            </p>
          )}
          <Box role="comparison" title="Compare" label="left side against right side" problems={problems} path={["comparison"]}>
            <div className="flex flex-wrap items-start gap-2">
              <TermBlock term={left} label="left side" path={["left side"]} problems={problems} context={context} bound={forall}
                onChange={(next) => onChange({ ...rule, left: next })} />
              <select aria-label="Comparison" className={`${SELECT} self-center font-medium`} value={rule.relation ?? "<="}
                onChange={(event) => onChange({ ...rule, relation: event.target.value as Constraint["relation"] })}>
                {RELATIONS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select>
              <TermBlock term={right} label="right side" path={["right side"]} problems={problems} context={context} bound={forall}
                onChange={(next) => onChange({ ...rule, right: next })} />
            </div>
          </Box>
        </div>
      </Box>
    </div>
  );
}

/** A goal term as boxes: what it counts. */
export function GoalBlocks({ label, expression, context, onChange }: {
  label: string;
  expression: Term;
  context: ModelContext;
  onChange: (next: Term) => void;
}) {
  const problems = checkGoal(expression, context);
  return (
    <div className="space-y-2" data-testid="goal-blocks">
      <Summary problems={problems} />
      <TermBlock term={expression} label={`what ${label} counts`} path={[]} problems={problems} context={context} bound={[]}
        onChange={onChange} />
    </div>
  );
}

/** Sentence: the rule read out in plain words, what it still needs, and the way into its boxes. */
export function RuleSentence({ rule, context, onEdit }: { rule: Constraint; context: ModelContext; onEdit: () => void }) {
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="rule-sentence">
      <p className="text-sm leading-relaxed text-slate-900">{ruleSentence(rule)}</p>
      <Summary problems={checkRule(rule, context)} />
      <button type="button" className="text-xs text-blue-700 underline" onClick={onEdit}>Change it in boxes</button>
    </div>
  );
}

export function GoalSentence({ expression, context, onEdit }: { expression: Term; context: ModelContext; onEdit: () => void }) {
  const text = termSentence(expression);
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="goal-sentence">
      <p className="text-sm leading-relaxed text-slate-900">Counts {text}.</p>
      <Summary problems={checkGoal(expression, context)} />
      <button type="button" className="text-xs text-blue-700 underline" onClick={onEdit}>Change it in boxes</button>
    </div>
  );
}
