/**
 * A rule or goal read out in plain words, for the Sentence view
 * (docs/design/nested-blocks.md, "Model → explanation"). Generated from the
 * IR alone, deterministically: the same model always reads the same way, and
 * nothing here is guessed.
 *
 *   for each d in day: sum(hours[p] for p in person) >= demand[d]
 *   → For every day d, the total of hours of p, over every person p, must be
 *     at least demand of d.
 */
import { FUNCTIONS } from "../ir";
import { cellText } from "../lib/irBlocks/catalogue";
import { describeWhen, type Binding, type Constraint, type Term } from "./terms";

const RELATION_WORDS: Record<string, string> = { "<=": "must be at most", ">=": "must be at least", "=": "must be exactly" };

function of(name: string, index: unknown[]): string {
  return index.length ? `${name} of ${index.map((cell) => cellText(cell)).join(", ")}` : name;
}

function where(binding: Binding): string {
  const filters = (binding.where ?? []).map((f) => {
    const op = f.op === "=" ? "is" : f.op === "!=" ? "is not" : f.op === "in" ? "is one of" : f.op === "notIn" ? "is not one of" : f.op;
    return `${f.attr} ${op} ${Array.isArray(f.value) ? f.value.join(", ") : typeof f.value === "object" && f.value !== null ? cellText(f.value) : String(f.value)}`;
  });
  const walk = binding.via ? ` linked by ${binding.via.rel}` : "";
  return `every ${binding.set} ${binding.index}${walk}${filters.length ? ` whose ${filters.join(" and ")}` : ""}`;
}

/** `-1 × x` reads as "minus x" inside a sum of terms. */
function negated(term: Term): Term | null {
  if ("mul" in term && "const" in term.mul[0] && term.mul[0].const === -1) return term.mul[1];
  return null;
}

export function termSentence(term: Term): string {
  if ("const" in term) return String(term.const);
  if ("var" in term) return of(term.var, term.index);
  if ("par" in term) return of(term.par, term.index);
  if ("attr" in term) return term.attr.along ? `the ${term.attr.along} of ${term.attr.name} along ${term.attr.of}` : `${term.attr.name} of ${term.attr.of}`;
  if ("sum" in term) return `the total of ${termSentence(term.sum)}, over ${term.over.map(where).join(" and ")}`;
  if ("add" in term) {
    return term.add
      .map((part, i) => {
        const minus = negated(part);
        if (minus) return `minus ${termSentence(minus)}`;
        return i === 0 ? termSentence(part) : `plus ${termSentence(part)}`;
      })
      .join(" ");
  }
  if ("mul" in term) {
    const minus = negated(term);
    if (minus) return `minus ${termSentence(minus)}`;
    return `${termSentence(term.mul[0])} times ${termSentence(term.mul[1])}`;
  }
  if ("fn" in term) return `${FUNCTIONS[term.fn]?.text ?? term.fn} of ${termSentence(term.of)}`;
  if ("predict" in term) return `what ${term.predict} predicts from ${term.of.map(termSentence).join(" and ")}`;
  return `a curve of ${of(term.pwl.var, term.pwl.index)} through ${term.points.length} points`;
}

export function ruleSentence(rule: Constraint): string {
  if (rule.left == null || rule.right == null) return "This rule does not say anything yet.";
  const scope = (rule.forall ?? []).length ? `For ${(rule.forall ?? []).map(where).join(" and ")}, ` : "";
  const condition = describeWhen(rule.when);
  // A total's "over every …" clause needs a pause before the comparison.
  const pause = "sum" in rule.left ? "," : "";
  const body = `${termSentence(rule.left)}${pause} ${RELATION_WORDS[rule.relation ?? "<="] ?? rule.relation} ${termSentence(rule.right)}`;
  const strength = rule.severity === "soft" ? ` It is preferred, not required (weight ${rule.weight ?? 1}).` : "";
  const text = `${scope}${scope ? body : body.charAt(0).toUpperCase() + body.slice(1)}${condition ? `, ${condition}` : ""}.`;
  return `${text}${strength}`;
}
