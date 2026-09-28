import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { goalEquation, parseGoal, parseRule, printRule, ruleEquation, withEquation } from "./formula";
import type { Binding, Constraint, ModelContext, Term } from "./terms";

const HERE = dirname(fileURLToPath(import.meta.url));
const TEMPLATES = resolve(HERE, "../../../backend/tests/template_irs.json");

const CONTEXT: ModelContext = {
  sets: ["person", "day", "shift", "item"],
  setIds: {},
  attributes: { person: [{ name: "team", data_type: "text" }, { name: "cap", data_type: "number" }] },
  variables: {
    hours: { index: ["person"], domain: "continuous" },
    assign: { index: ["person", "day", "shift"], domain: "binary" },
    x: { index: ["item"], domain: "integer" },
  },
  parameters: { demand: { index: ["day"] }, budget: { index: [] }, next_day: { index: ["day"] } },
  relationships: [],
};

describe("equations for rules", () => {
  it("reads a sum over a set with its limit", () => {
    const parsed = parseRule("sum(hours[p] for p in person) = 120", CONTEXT);
    expect(parsed).toEqual({
      ok: true,
      value: { left: { sum: { var: "hours", index: ["p"] }, over: [{ index: "p", set: "person" }] }, relation: "=", right: { const: 120 } },
    });
  });

  it("reads for each, filters, parameters, products and functions", () => {
    const parsed = parseRule(
      'for each d in day: sum(assign[p, d, s] for p in person where team = "north" and cap >= 2, s in shift) >= demand[d] + -1 * budget',
      CONTEXT,
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.forall).toEqual([{ index: "d", set: "day" }]);
    const over = (parsed.value.left as { over: Binding[] }).over;
    expect(over[0].where).toEqual([{ attr: "team", op: "=", value: "north" }, { attr: "cap", op: ">=", value: 2 }]);
    expect(parsed.value.right).toEqual({ add: [{ par: "demand", index: ["d"] }, { mul: [{ const: -1 }, { par: "budget", index: [] }] }] });
    expect(parseRule("sum(abs(x[i]) for i in item) <= 4", CONTEXT).ok).toBe(true);
    expect(parseRule("sum(cap[p] * hours[p] for p in person) <= 40", CONTEXT)).toMatchObject({
      ok: true, value: { left: { sum: { mul: [{ attr: { of: "p", name: "cap" } }, { var: "hours", index: ["p"] }] } } },
    });
  });

  it("explains what is wrong, and where", () => {
    const cases: [string, RegExp][] = [
      ["sum(hour[p] for p in person) = 1", /“hour” is not a variable.*did you mean “hours”/],
      ["hours[p] = 1", /“p” is not bound here/],
      ["sum(assign[p] for p in person) = 1", /“assign” takes 3 indices \(person, day, shift\), got 1/],
      ["sum(hours[p] for p in people) = 1", /“people” is not a set/],
      ["sum(hours[p] for p in person) < 1", /<=, >= or =/],
      ["(1 + 2 = 3", /close the bracket/],
      ["sum(hours[p] for p in person where colour = 1) = 1", /not an attribute of person/],
    ];
    for (const [text, message] of cases) {
      const parsed = parseRule(text, CONTEXT);
      expect(parsed.ok, text).toBe(false);
      if (!parsed.ok) {
        expect(parsed.message).toMatch(message);
        expect(parsed.at).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("keeps a rule's other keys when its equation changes", () => {
    const rule: Constraint = { id: "c_total", note: "cover it", severity: "soft", weight: 3, left: { const: 1 }, relation: "<=", right: { const: 2 } };
    const parsed = parseRule("for each d in day: demand[d] >= 1", CONTEXT);
    if (!parsed.ok) throw new Error(parsed.message);
    expect(withEquation(rule, parsed.value)).toEqual({
      id: "c_total", note: "cover it", severity: "soft", weight: 3,
      forall: [{ index: "d", set: "day" }], left: { par: "demand", index: ["d"] }, relation: ">=", right: { const: 1 },
    });
  });

  it("offers no equation for shapes it cannot write back exactly", () => {
    const walk: Constraint = { id: "w", left: { sum: { const: 1 }, over: [{ index: "u", set: "person", via: { rel: "reports_to", to: "p" } }] }, relation: "<=", right: { const: 3 }, forall: [{ index: "p", set: "person" }] };
    expect(ruleEquation(walk, CONTEXT)).toBeNull();
    expect(ruleEquation({ id: "s", no_overlap: { interval: { var: "x", index: [] }, over: [] } } as Constraint, CONTEXT)).toBeNull();
    expect(ruleEquation({ id: "empty" }, CONTEXT)).toBeNull();
  });
});

/** The names an IR uses, as a context the parser can resolve them in. */
function contextOf(ir: Record<string, unknown>): ModelContext {
  const attributes: Record<string, { name: string; data_type: string }[]> = {};
  const add = (set: string, name: string) => {
    attributes[set] ??= [];
    if (!attributes[set].some((a) => a.name === name)) attributes[set].push({ name, data_type: "number" });
  };
  const visit = (node: unknown, scope: Record<string, string>) => {
    if (Array.isArray(node)) return node.forEach((child) => visit(child, scope));
    if (!node || typeof node !== "object") return;
    const record = node as Record<string, unknown>;
    const inner = { ...scope };
    for (const key of ["forall", "over"]) {
      for (const binding of (record[key] as Binding[] | undefined) ?? []) {
        inner[binding.index] = binding.set;
        for (const filter of binding.where ?? []) add(binding.set, filter.attr);
      }
    }
    const attr = record.attr as { of?: string; name?: string } | undefined;
    if (attr?.of && attr.name && inner[attr.of]) add(inner[attr.of], attr.name);
    Object.values(record).forEach((child) => visit(child, inner));
  };
  visit(ir.constraints, {});
  visit(ir.objective, {});
  const decl = (key: string) => Object.fromEntries(Object.entries((ir[key] ?? {}) as Record<string, { index?: string[]; domain?: string }>)
    .map(([name, spec]) => [name, { index: spec.index ?? [], domain: spec.domain ?? "continuous" }]));
  return {
    sets: ir.sets as string[],
    setIds: {},
    attributes,
    variables: decl("variables"),
    parameters: decl("parameters"),
    relationships: [],
  };
}

describe.skipIf(!existsSync(TEMPLATES))("every template's rules and goals", () => {
  const templates = existsSync(TEMPLATES) ? (JSON.parse(readFileSync(TEMPLATES, "utf8")) as Record<string, Record<string, unknown>>) : {};

  it("read back exactly from their equations, for every rule that has one", () => {
    let written = 0;
    for (const [name, ir] of Object.entries(templates)) {
      const context = contextOf(ir);
      for (const rule of ir.constraints as Constraint[]) {
        const text = ruleEquation(rule, context);
        if (text === null) continue;
        written += 1;
        const back = parseRule(text, context);
        expect(back.ok, `${name}/${rule.id}: ${text}`).toBe(true);
        if (back.ok) expect(withEquation(rule, back.value), `${name}/${rule.id}`).toEqual({ ...rule, ...(rule.forall?.length ? {} : { forall: undefined }) } as Constraint);
      }
      const objective = ir.objective as { terms?: { expression?: Term }[] } | undefined;
      for (const term of objective?.terms ?? []) {
        const text = goalEquation(term.expression, context);
        if (text === null) continue;
        written += 1;
        expect(parseGoal(text, context)).toEqual({ ok: true, value: term.expression });
      }
    }
    // Most template rules are plain arithmetic: the equation view must cover them.
    expect(written).toBeGreaterThan(10);
  });

  it("writes the load balance model as a modeller would", () => {
    const ir = templates.load_balance;
    const context = contextOf(ir);
    const texts = (ir.constraints as Constraint[]).map((rule) => ruleEquation(rule, context));
    expect(texts.every((text) => text !== null)).toBe(true);
    expect(texts.join("\n")).toMatch(/sum\(hours\[\w+\] for \w+ in person\) = /);
    expect(printRule((ir.constraints as Constraint[])[0])).toBe(texts[0]);
  });
});
