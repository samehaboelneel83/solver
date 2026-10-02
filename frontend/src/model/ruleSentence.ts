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
import { describeWhen, isIndexFilter, type Binding, type Constraint, type IrFilter, type Term } from "./terms";
import { walkWords } from "./walkWords";
import { entryWords, OP_WORDS } from "./whereWords";

const RELATION_WORDS: Record<string, string> = { "<=": "must be at most", ">=": "must be at least", "=": "must be exactly" };

function of(name: string, index: unknown[]): string {
  return index.length ? `${name} of ${index.map((cell) => cellText(cell)).join(", ")}` : name;
}

/** Relationships, by name: which of them are hierarchies, for "below" and "above". */
type Rels = readonly { name: string; hierarchy?: boolean }[];

function where(binding: Binding, rels: Rels): string {
  const said = (f: IrFilter) => {
    const op = OP_WORDS[f.op] ?? f.op;
    return `${f.attr} ${op} ${Array.isArray(f.value) ? f.value.join(", ") : typeof f.value === "object" && f.value !== null ? cellText(f.value) : String(f.value)}`;
  };
  // Another item of the set is not a field of this one: "every site c2 after c", not "whose after c"
  // (benchmark re-test, October 2026).
  const entries = binding.where ?? [];
  const against = entries.filter(isIndexFilter).map((entry) => entryWords(entry, said));
  const filters = entries.filter((entry) => !isIndexFilter(entry)).map((entry) => entryWords(entry, said));
  const tree = rels.some((r) => r.name === binding.via?.rel && r.hierarchy);
  const walk = binding.via ? ` ${walkWords(binding.via, tree)}` : "";
  return `every ${binding.set} ${binding.index}${against.length ? ` ${against.join(" and ")}` : ""}${
    filters.length ? `${against.length ? "," : ""} whose ${filters.join(" and ")}${walk ? "," : ""}` : ""}${walk}`;
}

/** `-1 × x` reads as "minus x" inside a sum of terms. */
function negated(term: Term): Term | null {
  if ("mul" in term && "const" in term.mul[0] && term.mul[0].const === -1) return term.mul[1];
  return null;
}

export function termSentence(term: Term, rels: Rels = []): string {
  const t = (part: Term) => termSentence(part, rels);
  if ("const" in term) return String(term.const);
  if ("var" in term) return of(term.var, term.index);
  if ("par" in term) return of(term.par, term.index);
  if ("attr" in term) return term.attr.along ? `the ${term.attr.along} of ${term.attr.name} along ${term.attr.of}` : `${term.attr.name} of ${term.attr.of}`;
  if ("sum" in term) return `the total of ${t(term.sum)}, over ${term.over.map((b) => where(b, rels)).join(" and ")}`;
  if ("add" in term) {
    return term.add
      .map((part, i) => {
        const minus = negated(part);
        if (minus) return `minus ${t(minus)}`;
        return i === 0 ? t(part) : `plus ${t(part)}`;
      })
      .join(" ");
  }
  if ("mul" in term) {
    // A sum inside a product keeps its brackets: "price times (a plus b)" is not "price times a plus b"
    // (benchmark re-test, October 2026).
    const grouped = (part: Term) => ("add" in part && part.add.length > 1 ? `(${t(part)})` : t(part));
    const minus = negated(term);
    if (minus) return `minus ${grouped(minus)}`;
    return `${grouped(term.mul[0])} times ${grouped(term.mul[1])}`;
  }
  if ("fn" in term) return `${FUNCTIONS[term.fn]?.text ?? term.fn} of ${t(term.of)}`;
  if ("predict" in term) return `what ${term.predict} predicts from ${term.of.map(t).join(" and ")}`;
  return `a curve of ${of(term.pwl.var, term.pwl.index)} through ${term.points.length} points`;
}

export function ruleSentence(rule: Constraint, rels: Rels = []): string {
  if (rule.left == null || rule.right == null) return "This rule does not say anything yet.";
  const scope = (rule.forall ?? []).length ? `For ${(rule.forall ?? []).map((b) => where(b, rels)).join(" and ")}, ` : "";
  const condition = describeWhen(rule.when);
  // A total's "over every …" clause needs a pause before the comparison.
  const pause = "sum" in rule.left ? "," : "";
  const body = `${termSentence(rule.left, rels)}${pause} ${RELATION_WORDS[rule.relation ?? "<="] ?? rule.relation} ${termSentence(rule.right, rels)}`;
  const strength = rule.severity === "soft" ? ` It is preferred, not required (weight ${rule.weight ?? 1}).` : "";
  const text = `${scope}${scope ? body : body.charAt(0).toUpperCase() + body.slice(1)}${condition ? `, ${condition}` : ""}.`;
  return `${text}${strength}`;
}
