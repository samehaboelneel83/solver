/**
 * Rules and goals as equations -- the IR, written the way a modeller writes it:
 *
 *     for each d in day: sum(assign[e, d] for e in employee) >= demand[d]
 *     sum(hours[p] for p in person where team = "north") = 120
 *
 * This is only a view of the IR. `printRule` writes a rule's `forall`,
 * `left`, `relation` and `right` as text, and `parseRule` reads the text back
 * into exactly those keys. Everything else on a rule (id, note, strength,
 * weight, chance) is edited beside the equation and passes through
 * untouched.
 *
 * Not every IR shape has an equation. `ruleEquation` and `goalEquation` offer
 * the text only when parsing the printed text gives back the very same IR, so
 * the equation view can never quietly change a model. Curves, conditional
 * rules and scheduling, connected and route rules stay in the structure
 * editor.
 *
 * Grammar (one-to-one with the IR term kinds):
 *
 *     rule     := [ "for each" bindings ":" ] expr relation expr
 *     relation := "<=" | ">=" | "="
 *     expr     := product { ("+" | "-") product }
 *     product  := unary { "*" unary }
 *     unary    := "-" unary | atom
 *     atom     := number | "(" expr ")" | "sum(" expr "for" bindings ")"
 *              |  function "(" expr ")" | name "[" cells "]" | name
 *     bindings := binding { "," binding }
 *     binding  := index "in" set [ walk ] [ "where" filter { "and" filter } ]
 *     walk     := ("from" | "to") index "by" relationship [ "depth" ("any" | "any_or_self") ] [ "as" name ]
 *     filter   := attribute op value      op: = != < <= > >= in "not in"
 *     atom     |= "path_" combination "(" attribute "[" link "]" ")"   combination: sum min max product count
 *
 * A walk: `e in employee from m by manages depth any as r` is every employee
 * below m along manages, in one or more steps, each link named r;
 * `weight[r]` reads one link's number and `path_sum(weight[r])` adds them up
 * along a walk of many steps.
 */
import { FUNCTIONS, FILTER_OPERATORS, PATH_COMBINATIONS, RELATIONS, TRAVERSAL_DEPTHS, type PathCombination, type Relation, type TraversalDepth } from "../ir";
import { cellText } from "../lib/irBlocks/catalogue";
import { edgeAttributes, type Binding, type Constraint, type IrFilter, type ModelContext, type Term, type Via } from "./terms";

// --- printing ----------------------------------------------------------------

function printValue(value: unknown): string {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) return cellText(value);
  return JSON.stringify(value);
}

function printFilter(filter: IrFilter): string {
  const op = filter.op === "notIn" ? "not in" : filter.op;
  return `${filter.attr} ${op} ${printValue(filter.value)}`;
}

function printWalk(via: Via): string {
  const from = via.from !== undefined;
  const depth = via.depth && via.depth !== "one" ? ` depth ${via.depth}` : "";
  const edge = via.as ? ` as ${via.as}` : "";
  return ` ${from ? "from" : "to"} ${from ? via.from : via.to} by ${via.rel}${depth}${edge}`;
}

export function printBinding(binding: Binding): string {
  const where = binding.where?.length ? ` where ${binding.where.map(printFilter).join(" and ")}` : "";
  return `${binding.index} in ${binding.set}${binding.via ? printWalk(binding.via) : ""}${where}`;
}

function printNumber(value: number): string {
  return Number.isFinite(value) ? String(value) : "NaN";
}

/** `term` as text. Parentheses keep the IR's own nesting, so the text reads
 * back to the same tree. */
export function printTerm(term: Term): string {
  if ("const" in term) return printNumber(term.const);
  if ("var" in term) return term.index.length ? `${term.var}[${term.index.map(cellText).join(", ")}]` : term.var;
  if ("par" in term) return term.index.length ? `${term.par}[${term.index.map(cellText).join(", ")}]` : term.par;
  if ("attr" in term) {
    const read = `${term.attr.name}[${term.attr.of}]`;
    return term.attr.along ? `path_${term.attr.along}(${read})` : read;
  }
  if ("sum" in term) return `sum(${printTerm(term.sum)} for ${term.over.map(printBinding).join(", ")})`;
  if ("fn" in term) return `${term.fn}(${printTerm(term.of)})`;
  if ("predict" in term) return `predict ${term.predict}(${term.of.map(printTerm).join(", ")})`;
  if ("add" in term) {
    return term.add
      .map((part, i) => {
        const text = "add" in part ? `(${printTerm(part)})` : printTerm(part);
        if (i === 0) return text;
        // `a - 3` and `a - 2 * b` rather than `a + -3` and `a + -2 * b`.
        if ("const" in part && part.const < 0) return `- ${printNumber(-part.const)}`;
        if ("mul" in part && "const" in part.mul[0] && part.mul[0].const < 0) {
          const k = -part.mul[0].const;
          const rest = part.mul[1];
          const restText = "add" in rest || "mul" in rest ? `(${printTerm(rest)})` : printTerm(rest);
          return k === 1 ? `- ${restText}` : `- ${printNumber(k)} * ${restText}`;
        }
        return `+ ${text}`;
      })
      .join(" ");
  }
  if ("mul" in term) {
    const [left, right] = term.mul;
    const wrapLeft = "add" in left;
    const wrapRight = "add" in right || "mul" in right;
    return `${wrapLeft ? `(${printTerm(left)})` : printTerm(left)} * ${wrapRight ? `(${printTerm(right)})` : printTerm(right)}`;
  }
  return "?";
}

export function printRule(rule: Pick<Constraint, "forall" | "left" | "relation" | "right">): string {
  const head = rule.forall?.length ? `for each ${rule.forall.map(printBinding).join(", ")}: ` : "";
  return `${head}${rule.left ? printTerm(rule.left) : "?"} ${rule.relation ?? "?"} ${rule.right ? printTerm(rule.right) : "?"}`;
}

// --- tokens ------------------------------------------------------------------

type Token =
  | { kind: "num"; value: number; at: number; end: number }
  | { kind: "name"; value: string; at: number; end: number }
  | { kind: "str"; value: string; at: number; end: number }
  | { kind: "op"; value: string; at: number; end: number }
  | { kind: "end"; value: ""; at: number; end: number };

export class FormulaError extends Error {
  constructor(message: string, public at: number, public end: number = at + 1) {
    super(message);
  }
}

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (/\s/.test(ch)) {
      i += 1;
      continue;
    }
    const number = /^(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?/.exec(text.slice(i));
    if (number) {
      tokens.push({ kind: "num", value: Number(number[0]), at: i, end: i + number[0].length });
      i += number[0].length;
      continue;
    }
    const name = /^[A-Za-z_][A-Za-z0-9_]*/.exec(text.slice(i));
    if (name) {
      tokens.push({ kind: "name", value: name[0], at: i, end: i + name[0].length });
      i += name[0].length;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      let raw = '"';
      while (j < text.length && text[j] !== '"') {
        raw += text[j] === "\\" ? text[j] + (text[j + 1] ?? "") : text[j];
        j += text[j] === "\\" ? 2 : 1;
      }
      if (j >= text.length) throw new FormulaError("This text is missing its closing quote.", i, text.length);
      tokens.push({ kind: "str", value: JSON.parse(raw + '"') as string, at: i, end: j + 1 });
      i = j + 1;
      continue;
    }
    const two = text.slice(i, i + 2);
    if (["<=", ">=", "!=", "=="].includes(two)) {
      tokens.push({ kind: "op", value: two === "==" ? "=" : two, at: i, end: i + 2 });
      i += 2;
      continue;
    }
    const symbol = ch === "≤" ? "<=" : ch === "≥" ? ">=" : ch === "×" ? "*" : ch === "−" ? "-" : ch;
    if ("+-*()[],:=<>".includes(symbol)) {
      tokens.push({ kind: "op", value: symbol, at: i, end: i + 1 });
      i += 1;
      continue;
    }
    throw new FormulaError(`“${ch}” is not part of an equation.`, i);
  }
  tokens.push({ kind: "end", value: "", at: text.length, end: text.length });
  return tokens;
}

// --- parsing -----------------------------------------------------------------

const RULE_RELATIONS = new Set<string>(RELATIONS);

class Parser {
  private at = 0;
  private scope: Binding[][] = [];
  constructor(private tokens: Token[], private context: ModelContext) {}

  private peek(offset = 0): Token {
    return this.tokens[Math.min(this.at + offset, this.tokens.length - 1)];
  }
  private next(): Token {
    const token = this.peek();
    this.at += 1;
    return token;
  }
  private isOp(value: string, offset = 0): boolean {
    const token = this.peek(offset);
    return token.kind === "op" && token.value === value;
  }
  private isWord(value: string, offset = 0): boolean {
    const token = this.peek(offset);
    return token.kind === "name" && token.value === value;
  }
  private expectOp(value: string, what: string) {
    const token = this.next();
    if (token.kind !== "op" || token.value !== value) throw new FormulaError(`Expected “${value}” ${what}.`, token.at, token.end);
  }
  private expectWord(value: string, what: string) {
    const token = this.next();
    if (token.kind !== "name" || token.value !== value) throw new FormulaError(`Expected “${value}” ${what}.`, token.at, token.end);
  }
  private bound(name: string): Binding | undefined {
    for (let level = this.scope.length - 1; level >= 0; level -= 1) {
      const found = this.scope[level].find((binding) => binding.index === name);
      if (found) return found;
    }
    return undefined;
  }

  end() {
    const token = this.peek();
    if (token.kind !== "end") throw new FormulaError("Unexpected text after the end of the equation.", token.at, token.end);
  }

  rule(): Pick<Constraint, "forall" | "left" | "relation" | "right"> {
    let forall: Binding[] = [];
    if (this.isWord("for") && this.isWord("each", 1)) {
      this.next();
      this.next();
      forall = this.bindings(":");
      this.expectOp(":", "after the “for each” part");
    }
    this.scope.push(forall);
    const left = this.expr();
    const token = this.next();
    if (token.kind !== "op" || !RULE_RELATIONS.has(token.value)) {
      throw new FormulaError("A rule compares two sides with <=, >= or =.", token.at, token.end);
    }
    const right = this.expr();
    this.scope.pop();
    return { ...(forall.length ? { forall } : {}), left, relation: token.value as Relation, right };
  }

  goal(): Term {
    return this.termIn([]);
  }

  /** A term inside a rule, where `bound` indices are already in scope. */
  termIn(bound: Binding[]): Term {
    this.scope.push(bound);
    const term = this.expr();
    this.scope.pop();
    return term;
  }

  /** A comma-separated list of bindings, with `bound` in scope, to the end. */
  bindingList(bound: Binding[]): Binding[] {
    this.scope.push(bound);
    const list: Binding[] = [];
    this.scope.push(list);
    for (;;) {
      list.push(this.binding());
      if (!this.isOp(",")) break;
      this.next();
    }
    this.scope.pop();
    this.scope.pop();
    return list;
  }

  private bindings(stop: string): Binding[] {
    const list: Binding[] = [];
    this.scope.push(list);
    for (;;) {
      list.push(this.binding());
      if (this.isOp(",")) {
        this.next();
        continue;
      }
      break;
    }
    this.scope.pop();
    if (!this.isOp(stop)) {
      const token = this.peek();
      throw new FormulaError(`Expected “${stop}” after “${list.map(printBinding).join(", ")}”.`, token.at, token.end);
    }
    return list;
  }

  private binding(): Binding {
    const index = this.next();
    if (index.kind !== "name" || !/^[a-z][a-z0-9_]*$/.test(index.value)) {
      throw new FormulaError("Name an index here, such as “p” in “p in person”.", index.at, index.end);
    }
    this.expectWord("in", `after the index “${index.value}”`);
    const set = this.next();
    if (set.kind !== "name" || !this.context.sets.includes(set.value)) {
      throw new FormulaError(
        `“${set.kind === "end" ? "" : String(set.value)}” is not a set of this model${this.context.sets.length ? ` (${this.context.sets.join(", ")})` : ""}.`,
        set.at,
        set.end,
      );
    }
    const binding: Binding = { index: index.value, set: set.value };
    if (this.isWord("from") || this.isWord("to")) binding.via = this.walk(set.value);
    if (this.isWord("where")) {
      this.next();
      const where: IrFilter[] = [this.filter(set.value)];
      while (this.isWord("and")) {
        this.next();
        where.push(this.filter(set.value));
      }
      binding.where = where;
    }
    return binding;
  }

  /** `from m by manages depth any as r`: which item it starts at, along which relationship, how far, and the links' name. */
  private walk(set: string): Via {
    const end = this.next().value as "from" | "to";
    const anchor = this.next();
    if (anchor.kind !== "name" || !this.bound(anchor.value)) {
      throw new FormulaError(
        `A walk starts at an index bound before it, such as “m” in “for each m in employee”; “${String(anchor.value)}” is not.`,
        anchor.at,
        anchor.end,
      );
    }
    this.expectWord("by", `after “${end} ${anchor.value}”`);
    const rel = this.next();
    const known = this.context.relationships.find((r) => r.name === rel.value);
    if (rel.kind !== "name" || !known) {
      const names = this.context.relationships.map((r) => r.name);
      throw new FormulaError(
        `“${String(rel.value)}” is not a relationship of this model${names.length ? ` (${names.join(", ")})` : ""}.`,
        rel.at,
        rel.end,
      );
    }
    const reached = end === "from" ? known.to : known.from;
    if (reached !== set) {
      throw new FormulaError(`Walking ${known.name} ${end === "from" ? "from" : "back to"} its ${end === "from" ? known.from : known.to} reaches ${reached}, not ${set}.`, rel.at, rel.end);
    }
    const via: Via = { rel: known.name, [end]: anchor.value } as Via;
    if (this.isWord("depth")) {
      this.next();
      const depth = this.next();
      if (depth.kind !== "name" || !(TRAVERSAL_DEPTHS as readonly string[]).includes(depth.value)) {
        throw new FormulaError("A walk goes depth one, any or any_or_self.", depth.at, depth.end);
      }
      if (depth.value !== "one") via.depth = depth.value as TraversalDepth;
    }
    if (this.isWord("as")) {
      this.next();
      const edge = this.next();
      if (edge.kind !== "name" || !/^[a-z][a-z0-9_]*$/.test(edge.value) || this.bound(edge.value)) {
        throw new FormulaError("Name the links with a new name, such as “as r”.", edge.at, edge.end);
      }
      via.as = edge.value;
    }
    return via;
  }

  /** The link a walk in scope names with `as`. */
  private edge(name: string): { rel: string; path: boolean } | undefined {
    for (let level = this.scope.length - 1; level >= 0; level -= 1) {
      const found = this.scope[level].find((binding) => binding.via?.as === name);
      if (found?.via) return { rel: found.via.rel, path: (found.via.depth ?? "one") !== "one" };
    }
    return undefined;
  }

  private filter(set: string): IrFilter {
    const attr = this.next();
    const known = this.context.attributes[set] ?? [];
    if (attr.kind !== "name" || !known.some((a) => a.name === attr.value)) {
      throw new FormulaError(
        `“${String(attr.value)}” is not an attribute of ${set}${known.length ? ` (${known.map((a) => a.name).join(", ")})` : ""}.`,
        attr.at,
        attr.end,
      );
    }
    let op: string;
    const token = this.next();
    if (token.kind === "name" && token.value === "in") op = "in";
    else if (token.kind === "name" && token.value === "not" && this.isWord("in")) {
      this.next();
      op = "notIn";
    } else if (token.kind === "op" && (FILTER_OPERATORS as readonly string[]).includes(token.value)) op = token.value;
    else throw new FormulaError("Compare with =, !=, <, <=, >, >=, in or not in.", token.at, token.end);
    return { attr: attr.value, op, value: this.value() };
  }

  private value(): unknown {
    const token = this.next();
    if (token.kind === "str" || token.kind === "num") return token.value;
    if (token.kind === "op" && token.value === "-" && this.peek().kind === "num") return -(this.next().value as number);
    if (token.kind === "name" && (token.value === "true" || token.value === "false")) return token.value === "true";
    if (token.kind === "name" && token.value === "null") return null;
    if (token.kind === "op" && token.value === "[") {
      const items: unknown[] = [];
      if (!this.isOp("]")) {
        items.push(this.value());
        while (this.isOp(",")) {
          this.next();
          items.push(this.value());
        }
      }
      this.expectOp("]", "to close the list");
      return items;
    }
    if (token.kind === "name" && this.isOp("[")) {
      this.next();
      const index = this.cells(token.value);
      return { par: token.value, index };
    }
    throw new FormulaError("Expected a value: a number, \"text\", true, false or a [list].", token.at, token.end);
  }

  private expr(): Term {
    const parts: Term[] = [this.product()];
    while (this.isOp("+") || this.isOp("-")) {
      const minus = this.next().value === "-";
      const part = this.product();
      parts.push(minus ? negate(part) : part);
    }
    return parts.length === 1 ? parts[0] : { add: parts };
  }

  private product(): Term {
    let term = this.unary();
    while (this.isOp("*")) {
      this.next();
      term = { mul: [term, this.unary()] };
    }
    return term;
  }

  private unary(): Term {
    if (this.isOp("-")) {
      this.next();
      if (this.peek().kind === "num") return { const: -(this.next().value as number) };
      return negate(this.unary());
    }
    return this.atom();
  }

  private atom(): Term {
    const token = this.next();
    if (token.kind === "num") return { const: token.value };
    if (token.kind === "op" && token.value === "(") {
      const inner = this.expr();
      this.expectOp(")", "to close the bracket");
      return inner;
    }
    if (token.kind !== "name") {
      throw new FormulaError(token.kind === "end" ? "The equation stops too early." : `Unexpected “${token.value}”.`, token.at, token.end);
    }
    const name = token.value;
    if (name === "sum" && this.isOp("(")) {
      this.next();
      const start = this.at;
      // Read the bindings first (they follow `for`), then the summed term in their scope.
      let depth = 0;
      let forAt = -1;
      for (let i = this.at; i < this.tokens.length; i += 1) {
        const t = this.tokens[i];
        if (t.kind === "op" && (t.value === "(" || t.value === "[")) depth += 1;
        if (t.kind === "op" && (t.value === ")" || t.value === "]")) {
          if (depth === 0) break;
          depth -= 1;
        }
        if (depth === 0 && t.kind === "name" && t.value === "for") {
          forAt = i;
          break;
        }
      }
      if (forAt === -1) throw new FormulaError("A sum says what it runs over: sum(… for i in set).", token.at, token.end);
      this.at = forAt + 1;
      const over = this.bindings(")");
      const close = this.at;
      this.at = start;
      this.scope.push(over);
      const summed = this.expr();
      this.scope.pop();
      if (this.at !== forAt) {
        const stray = this.peek();
        throw new FormulaError("Expected “for” after the summed term.", stray.at, stray.end);
      }
      this.at = close;
      this.expectOp(")", "to close the sum");
      return { sum: summed, over };
    }
    if (name === "predict" && this.peek().kind === "name") {
      const model = this.next();
      const called = String(model.value);
      const predictors = this.context.predictors ?? {};
      if (!(called in predictors)) {
        const near = closest(called, Object.keys(predictors));
        throw new FormulaError(
          `“${called}” is not a predictor this model declares${near ? `; did you mean “${near}”?` : "."}`,
          model.at,
          model.end,
        );
      }
      this.expectOp("(", `after predict ${called}`);
      const of: Term[] = [];
      if (!this.isOp(")")) {
        of.push(this.expr());
        while (this.isOp(",")) {
          this.next();
          of.push(this.expr());
        }
      }
      this.expectOp(")", `to close predict ${called}(…)`);
      const inputs = predictors[called].inputs;
      if (of.length !== inputs) {
        throw new FormulaError(
          `“${called}” reads ${inputs} ${inputs === 1 ? "input" : "inputs"}, got ${of.length}.`,
          model.at,
          model.end,
        );
      }
      return { predict: called, of };
    }
    const combination = name.startsWith("path_") ? name.slice(5) : null;
    if (combination !== null && this.isOp("(")) {
      if (!(PATH_COMBINATIONS as readonly string[]).includes(combination)) {
        throw new FormulaError(`Along a path, a number is combined by ${PATH_COMBINATIONS.map((c) => `path_${c}`).join(", ")}.`, token.at, token.end);
      }
      this.next();
      const read = this.atom();
      if (!("attr" in read)) throw new FormulaError(`${name}(…) reads a link's number, such as ${name}(weight[r]).`, token.at, token.end);
      const link = this.edge(read.attr.of);
      if (!link?.path) {
        throw new FormulaError(`“${read.attr.of}” is not the links of a walk of many steps, so there is nothing to combine.`, token.at, token.end);
      }
      this.expectOp(")", `to close ${name}(…)`);
      return { attr: { ...read.attr, along: combination as PathCombination } };
    }
    if (name in FUNCTIONS && this.isOp("(")) {
      this.next();
      const of = this.expr();
      this.expectOp(")", `to close ${name}(…)`);
      return { fn: name, of };
    }
    const variable = this.context.variables[name];
    const parameter = this.context.parameters[name];
    const attribute =
      Object.values(this.context.attributes).some((list) => list.some((a) => a.name === name)) ||
      this.context.relationships.some((r) => (r.attributes ?? []).some((a) => a.name === name));
    if (!variable && !parameter && !attribute) {
      // Name the unknown word before anything inside its brackets.
      const near = closest(name, [...Object.keys(this.context.variables), ...Object.keys(this.context.parameters)]);
      throw new FormulaError(
        `“${name}” is not a variable, parameter or attribute of this model${near ? `; did you mean “${near}”?` : "."}`,
        token.at,
        token.end,
      );
    }
    const indexed = this.isOp("[");
    const index = indexed ? (this.next(), this.cells(name)) : [];
    const link = index.find((cell) => typeof cell === "string" && !this.bound(cell) && this.edge(cell));
    if ((variable || parameter) && link) {
      throw new FormulaError(`“${link}” names the links of a walk: read their numbers, such as weight[${link}], not ${name}[…].`, token.at, token.end);
    }
    if (variable) {
      this.checkArity(name, variable.index, index, token);
      return { var: name, index };
    }
    if (parameter) {
      this.checkArity(name, parameter.index, index, token);
      return { par: name, index };
    }
    if (indexed && index.length === 1 && typeof index[0] === "string") {
      const link = this.edge(index[0]);
      if (link && edgeAttributes(this.context, link.rel).some((a) => a.name === name)) {
        return { attr: { of: index[0], name } };
      }
      const binding = this.bound(index[0]);
      if (binding && (this.context.attributes[binding.set] ?? []).some((a) => a.name === name)) {
        return { attr: { of: index[0], name } };
      }
    }
    const names = [...Object.keys(this.context.variables), ...Object.keys(this.context.parameters)];
    const near = closest(name, names);
    throw new FormulaError(
      `“${name}” is not a variable, parameter or attribute of this model${near ? `; did you mean “${near}”?` : "."}`,
      token.at,
      token.end,
    );
  }

  private cells(owner: string): string[] {
    const cells: unknown[] = [];
    if (!this.isOp("]")) {
      cells.push(this.cell(owner));
      while (this.isOp(",")) {
        this.next();
        cells.push(this.cell(owner));
      }
    }
    this.expectOp("]", `to close ${owner}[…]`);
    return cells as string[];
  }

  private cell(owner: string): unknown {
    const token = this.next();
    if (token.kind !== "name") throw new FormulaError(`Expected an index inside ${owner}[…].`, token.at, token.end);
    if (this.isOp("[")) {
      this.next();
      return { par: token.value, index: this.cells(token.value) };
    }
    if (!this.bound(token.value) && !this.edge(token.value)) {
      throw new FormulaError(
        `“${token.value}” is not bound here: add “for ${token.value} in <set>” to a sum or to “for each”.`,
        token.at,
        token.end,
      );
    }
    return token.value;
  }

  private checkArity(name: string, declared: string[], index: unknown[], token: Token) {
    if (declared.length !== index.length) {
      throw new FormulaError(
        `“${name}” takes ${declared.length} ${declared.length === 1 ? "index" : "indices"}${declared.length ? ` (${declared.join(", ")})` : ""}, got ${index.length}.`,
        token.at,
        token.end,
      );
    }
  }
}

/** The known name within two edits of `name`, nearest first -- a typo's intended word. */
function closest(name: string, names: string[]): string | undefined {
  const distance = (a: string, b: string) => {
    let row = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i += 1) {
      const next = [i];
      for (let j = 1; j <= b.length; j += 1) {
        next[j] = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      row = next;
    }
    return row[b.length];
  };
  return names
    .map((candidate) => ({ candidate, d: distance(name, candidate) }))
    .filter(({ d }) => d <= 2)
    .sort((x, y) => x.d - y.d)[0]?.candidate;
}

function negate(term: Term): Term {
  if ("const" in term) return { const: -term.const };
  // `- 2 * b` is the product -2 * b, as the printer writes it.
  if ("mul" in term && "const" in term.mul[0]) return { mul: [{ const: -term.mul[0].const }, term.mul[1]] };
  return { mul: [{ const: -1 }, term] };
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; message: string; at: number; end: number };

function attempt<T>(run: () => T): Parsed<T> {
  try {
    return { ok: true, value: run() };
  } catch (error) {
    if (error instanceof FormulaError) return { ok: false, message: error.message, at: error.at, end: error.end };
    throw error;
  }
}

/** Read a rule's equation into its `forall`, `left`, `relation` and `right`. */
export function parseRule(text: string, context: ModelContext): Parsed<Pick<Constraint, "forall" | "left" | "relation" | "right">> {
  return attempt(() => {
    const parser = new Parser(tokenize(text), context);
    const rule = parser.rule();
    parser.end();
    return rule;
  });
}

/** Read a goal's equation into its expression. */
export function parseGoal(text: string, context: ModelContext): Parsed<Term> {
  return attempt(() => {
    const parser = new Parser(tokenize(text), context);
    const term = parser.goal();
    parser.end();
    return term;
  });
}

/** Read one part of a rule, with the indices bound around it in scope. */
export function parseTermIn(text: string, context: ModelContext, bound: Binding[]): Parsed<Term> {
  return attempt(() => {
    const parser = new Parser(tokenize(text), context);
    const term = parser.termIn(bound);
    parser.end();
    return term;
  });
}

/** Read what a sum or a rule ranges over: `p in person where team = "north", d in day`. */
export function parseBindings(text: string, context: ModelContext, bound: Binding[]): Parsed<Binding[]> {
  return attempt(() => {
    const parser = new Parser(tokenize(text), context);
    const list = parser.bindingList(bound);
    parser.end();
    return list;
  });
}

// --- offered only when exact -----------------------------------------------

/** Deep equality that ignores key order: stored IR is often key-sorted, and
 * the parser builds keys in its own order. */
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((item, i) => same(item, b[i]));
  }
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  const keysA = Object.keys(a).filter((key) => (a as Record<string, unknown>)[key] !== undefined);
  const keysB = Object.keys(b).filter((key) => (b as Record<string, unknown>)[key] !== undefined);
  return keysA.length === keysB.length && keysA.every((key) => same((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]));
}

/** The rule as an equation, or null when it has none that reads back exactly. */
export function ruleEquation(rule: Constraint, context: ModelContext): string | null {
  if (!rule.left || !rule.right || !rule.relation || rule.when || rule.no_overlap || rule.cumulative || rule.connected || rule.route) {
    return null;
  }
  const text = printRule(rule);
  const back = parseRule(text, context);
  if (!back.ok) return null;
  const forall = rule.forall?.length ? rule.forall : undefined;
  return same(back.value.forall, forall) && same(back.value.left, rule.left) && same(back.value.relation, rule.relation) && same(back.value.right, rule.right)
    ? text
    : null;
}

/** A goal's expression as an equation, or null when it has none that reads back exactly. */
export function goalEquation(expression: Term | undefined, context: ModelContext): string | null {
  if (!expression) return null;
  const text = printTerm(expression);
  const back = parseGoal(text, context);
  return back.ok && same(back.value, expression) ? text : null;
}

/** Replace a rule's equation keys with parsed ones, keeping everything else. */
export function withEquation(rule: Constraint, parsed: Pick<Constraint, "forall" | "left" | "relation" | "right">): Constraint {
  const { forall: _forall, left: _left, relation: _relation, right: _right, ...rest } = rule;
  void _forall;
  void _left;
  void _relation;
  void _right;
  return { ...rest, ...(parsed.forall ? { forall: parsed.forall } : {}), left: parsed.left, relation: parsed.relation, right: parsed.right };
}
