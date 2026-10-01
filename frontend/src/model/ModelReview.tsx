import type { FormDraft } from "./draftIr";
import { referencesOf } from "./declarations";
import { fieldsRead } from "./fieldsRead";
import { printRule, printTerm } from "./formula";
import { describeConnected, describeRoute, describeSchedule, describeWhen, type Constraint } from "./terms";

/**
 * The whole model on one readable page, before it is published (Epic UX, U-3):
 * what it is about, what it decides, the data it reads with units, every rule
 * in words, the goal -- and what looks unfinished.
 */
export default function ModelReview({ draft, units = {}, planner = [], wouldSolve = null }: {
  draft: FormDraft;
  units?: Record<string, string | null | undefined>;
  /** The server's classification, in a planner's words (`POST /classify`). */
  planner?: string[];
  wouldSolve?: string | null;
}) {
  const notes = [...reviewNotes(draft), ...unitNotes(draft, units)];
  const fields = fieldsRead(draft as unknown as Parameters<typeof fieldsRead>[0]);
  const kind = (domain: string) =>
    ({ binary: "yes or no", integer: "a whole number", continuous: "any number", interval: "a task in time" })[domain] ?? domain;
  const each = (index: string[]) => (index.length ? `for each ${index.join(" and ")}` : "one for the whole model");
  return (
    <section aria-label="Model review" className="mb-6 space-y-5 rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <div>
        <h2 className="text-base font-semibold">Review the whole model</h2>
        <p className="text-slate-600">Read it through before publishing: this is exactly what a published version will hold.</p>
      </div>
      {notes.length > 0 && (
        <div role="note" className="rounded border border-amber-300 bg-amber-50 p-3">
          <h3 className="font-medium">Worth a look</h3>
          <ul className="list-disc pl-5">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </div>
      )}
      <Part title="What it is about">
        {draft.sets.length ? <p>Every {draft.sets.join(", every ")} in the domain&rsquo;s data.</p> : <p>No sets: every decision is a single value.</p>}
      </Part>
      <Part title="What it decides">
        {Object.keys(draft.variables).length === 0 ? <p>Nothing yet.</p> : (
          <ul className="space-y-1">{Object.entries(draft.variables).map(([name, spec]) => (
            <li key={name}><span className="font-mono">{name}</span>: {kind(spec.domain)}, {each(spec.index)}
              {spec.domain === "interval" ? `, from ${spec.start} to ${spec.end}, lasting ${String(spec.size)}${spec.presence ? `, only if ${spec.presence}` : ""}`
                : spec.domain !== "binary" ? `, from ${spec.lower ?? 0} to ${spec.upper ?? "no stated limit"}` : ""}.
            </li>
          ))}</ul>
        )}
      </Part>
      <Part title="The data it reads">
        {Object.keys(draft.parameters).length === 0 && fields.length === 0 ? <p>No data: every number is written into the rules.</p> : (
          <ul className="space-y-1">
            {fields.map((field) => (
              <li key={`${field.set}.${field.name}`}><span className="font-mono">{field.name}</span>:{" "}
                {field.link ? `of each ${field.set} link` : `of each ${field.set}`}, from its records.</li>
            ))}
            {Object.entries(draft.parameters).map(([name, spec]) => (
              <li key={name}><span className="font-mono">{name}</span>: {each(spec.index)}{units[name] ? `, in ${units[name]}` : ""}.</li>
            ))}
          </ul>
        )}
      </Part>
      <Part title="What must be true">
        {draft.constraints.length === 0 ? <p>No rules: any values within the decisions&rsquo; bounds are acceptable.</p> : (
          <ol className="list-decimal space-y-2 pl-5">{draft.constraints.map((rule, i) => (
            <li key={`${i}-${rule.id}`}>
              <span className="font-medium">{rule.id}</span>{" "}
              <span className="text-slate-600">({rule.severity === "soft" ? `may bend, at ${rule.weight ?? 1} per unit` : "must hold"})</span>
              <p className="font-mono text-xs">{ruleInWords(rule)}</p>
              {describeWhen(rule.when) && <p className="text-xs text-slate-600">Applies {describeWhen(rule.when)}.</p>}
              {rule.note && <p className="text-xs text-slate-600">{rule.note}</p>}
            </li>
          ))}</ol>
        )}
      </Part>
      <Part title="What to make best">
        {draft.objective.terms.length === 0 ? <p>No goal: the solver looks for any answer that keeps every rule.</p> : (
          <>
            <p>{draft.objective.sense === "maximize" ? "Make as large as possible" : "Make as small as possible"}
              {draft.objective.mode === "lex" ? ", term by term in this order:" : draft.objective.terms.length > 1 ? ", the weighted total of:" : ":"}</p>
            <ul className="space-y-1">{draft.objective.terms.map((term) => (
              <li key={term.id}><span className="font-medium">{term.id}</span>{draft.objective.mode !== "lex" ? ` × ${term.weight}` : ""}:{" "}
                <span className="font-mono text-xs">{term.expression ? printTerm(term.expression) : "?"}</span></li>
            ))}</ul>
          </>
        )}
      </Part>
      {(planner.length > 0 || wouldSolve) && (
        <Part title="How it will be solved">
          {planner.map((line) => <p key={line}>{line}</p>)}
          {wouldSolve && <p>{wouldSolve}</p>}
        </Part>
      )}
    </section>
  );
}

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><h3 className="mb-1 font-medium text-slate-900">{title}</h3>{children}</div>;
}

export function ruleInWords(rule: Constraint): string {
  return describeSchedule(rule) ?? describeRoute(rule) ?? describeConnected(rule) ?? printRule(rule);
}

/** What looks unfinished: decisions nothing reads, data nothing uses, a goal-less model with no rules. */
export function reviewNotes(draft: FormDraft): string[] {
  const read = new Set<string>();
  const walk = (value: unknown) => JSON.stringify(value ?? null);
  const everything = walk(draft.constraints) + walk(draft.objective.terms);
  for (const rule of draft.constraints) {
    for (const side of [rule.left, rule.right]) if (side) referencesOf(side).names.forEach((n) => read.add(n));
  }
  for (const term of draft.objective.terms) if (term.expression) referencesOf(term.expression).names.forEach((n) => read.add(n));
  const parts = new Set(Object.values(draft.variables).flatMap((s) => [s.start, s.end, s.presence, typeof s.size === "string" ? s.size : undefined]));
  const notes: string[] = [];
  const unusedDecisions = Object.keys(draft.variables).filter((n) => !read.has(n) && !parts.has(n) && !everything.includes(`"var":"${n}"`));
  if (unusedDecisions.length) notes.push(`No rule or goal reads ${unusedDecisions.join(", ")}: the solver may set ${unusedDecisions.length > 1 ? "them" : "it"} to anything allowed.`);
  const unusedData = Object.keys(draft.parameters).filter((n) => !read.has(n) && !parts.has(n) && !everything.includes(`"par":"${n}"`));
  if (unusedData.length) notes.push(`${unusedData.join(", ")} ${unusedData.length > 1 ? "are" : "is"} declared but not read.`);
  const unbounded = Object.entries(draft.variables).filter(([, s]) => s.domain !== "binary" && s.domain !== "interval" && s.upper === undefined).map(([n]) => n);
  if (unbounded.length && draft.objective.terms.length) notes.push(`${unbounded.join(", ")} ${unbounded.length > 1 ? "have" : "has"} no maximum: if the goal rewards more of ${unbounded.length > 1 ? "them" : "it"}, the answer may run to the platform's ceiling.`);
  if (!draft.constraints.length && !draft.objective.terms.length) notes.push("There are no rules and no goal yet.");
  return notes;
}

type UnitTerm = { par?: string; var?: string; const?: number; attr?: unknown; sum?: UnitTerm; add?: UnitTerm[]; mul?: UnitTerm[]; neg?: UnitTerm };

/**
 * The unit a term is in, as far as the data's units say (improvement plan 5.4): a parameter carries
 * its own; a parameter times a decision keeps the parameter's (minutes x a yes/no is minutes); a sum
 * keeps its body's; anything else is not known, and is never guessed.
 */
export function unitOf(term: UnitTerm | undefined, units: Record<string, string | null | undefined>): string | null {
  if (!term || typeof term !== "object") return null;
  if (term.par) return (units[term.par] ?? "").trim().toLowerCase() || null;
  if (term.sum) return unitOf(term.sum, units);
  if (term.neg) return unitOf(term.neg, units);
  if (term.mul) {
    const known = term.mul.map((t) => unitOf(t, units)).filter((u): u is string => !!u);
    return known.length === 1 ? known[0] : null;
  }
  if (term.add) {
    const known = [...new Set(term.add.map((t) => unitOf(t, units)).filter((u): u is string => !!u))];
    return known.length === 1 ? known[0] : null;
  }
  return null;
}

/** Sums and comparisons that mix units -- minutes added to kilometres, a cost compared with a count. */
export function unitNotes(draft: FormDraft, units: Record<string, string | null | undefined>): string[] {
  const notes: string[] = [];
  const mixed = (term: UnitTerm | undefined, where: string) => {
    if (!term || typeof term !== "object") return;
    if (term.add) {
      const known = [...new Set(term.add.map((t) => unitOf(t, units)).filter((u): u is string => !!u))];
      if (known.length > 1) notes.push(`${where} adds ${known.join(" to ")}: check the units, or convert one first.`);
      term.add.forEach((t) => mixed(t, where));
    }
    if (term.sum) mixed(term.sum, where);
    if (term.mul) term.mul.forEach((t) => mixed(t, where));
  };
  for (const rule of draft.constraints) {
    const left = rule.left as UnitTerm | undefined;
    const right = rule.right as UnitTerm | undefined;
    mixed(left, rule.id);
    mixed(right, rule.id);
    const a = unitOf(left, units);
    const b = unitOf(right, units);
    if (a && b && a !== b) notes.push(`${rule.id} compares ${a} with ${b}: check the units.`);
  }
  for (const term of draft.objective.terms) mixed(term.expression as UnitTerm | undefined, `Goal ${term.id}`);
  return notes;
}
