import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { goalEquation, parseBindings, parseGoal, parseRule, parseTermIn, printRule, ruleEquation, withEquation } from "./formula";
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

  it("reads a yes/no field on its own as “is yes”, and with not as “is no” (user test: supervisors)", () => {
    const withFlag: ModelContext = { ...CONTEXT, attributes: { person: [...CONTEXT.attributes.person, { name: "supervisor", data_type: "boolean" }] } };
    const on = parseRule("for each d in day: sum(assign[p, d, s] for p in person where supervisor and cap >= 2, s in shift) >= 1", withFlag);
    expect(on.ok && on.value.left).toMatchObject({ over: [{ where: [{ attr: "supervisor", op: "=", value: true }, { attr: "cap", op: ">=", value: 2 }] }, {}] });
    const off = parseRule("sum(hours[p] for p in person where not supervisor) <= 40", withFlag);
    expect(off.ok && off.value.left).toMatchObject({ over: [{ where: [{ attr: "supervisor", op: "=", value: false }] }] });
    const spelled = parseRule("sum(hours[p] for p in person where supervisor = true) <= 40", withFlag);
    expect(spelled.ok && spelled.value.left).toMatchObject({ over: [{ where: [{ attr: "supervisor", op: "=", value: true }] }] });
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
      // What a Python habit types, and what is written instead (improvement plan 4.1).
      ["sum(assign[p, d, s] for p in person for d in day, s in shift) = 1", /One “for” lists every set, separated by commas: for p in person, i in set/],
      ["sum(hours[p] for p in person if cap >= 2) = 1", /Write “where” instead of “if”.*p in person where capacity >= 6.*Compute from the map/],
      ["sum(p.cap * hours[p] for p in person) <= 40", /A record's field is written cap\[p\], not p\.cap/],
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

describe("predictions in equations", () => {
  const WITH_MODEL: ModelContext = { ...CONTEXT, predictors: { demand_model: { inputs: 2 } } };

  it("reads a trained model applied to its inputs, and writes it back the same", () => {
    const text = "for each d in day: predict demand_model(demand[d], 2 * budget) <= 5";
    const parsed = parseRule(text, WITH_MODEL);
    expect(parsed).toEqual({
      ok: true,
      value: {
        forall: [{ index: "d", set: "day" }],
        left: { predict: "demand_model", of: [{ par: "demand", index: ["d"] }, { mul: [{ const: 2 }, { par: "budget", index: [] }] }] },
        relation: "<=",
        right: { const: 5 },
      },
    });
    if (parsed.ok) expect(ruleEquation({ id: "p", ...parsed.value }, WITH_MODEL)).toBe(text);
  });

  it("names an unknown model, and a wrong number of inputs", () => {
    const unknown = parseRule("predict demand_modl(budget, budget) <= 5", WITH_MODEL);
    expect(unknown.ok).toBe(false);
    if (!unknown.ok) expect(unknown.message).toMatch(/“demand_modl” is not a predictor.*did you mean “demand_model”/);
    const short = parseRule("predict demand_model(budget) <= 5", WITH_MODEL);
    expect(short.ok).toBe(false);
    if (!short.ok) expect(short.message).toMatch(/reads 2 inputs, got 1/);
    expect(parseRule("predict demand_model(budget, budget) <= 5", CONTEXT).ok).toBe(false);
  });
});

describe("parts of an equation", () => {
  it("reads a part with the indices bound around it", () => {
    const outer = [{ index: "p", set: "person" }];
    expect(parseTermIn("2 * cap[p]", CONTEXT, outer)).toEqual({ ok: true, value: { mul: [{ const: 2 }, { attr: { of: "p", name: "cap" } }] } });
    const unbound = parseTermIn("hours[q]", CONTEXT, outer);
    expect(unbound.ok).toBe(false);
    if (!unbound.ok) expect(unbound.message).toMatch(/“q” is not bound here/);
  });

  it("reads what a sum ranges over, filters included", () => {
    expect(parseBindings('p in person where team = "north", d in day', CONTEXT, [])).toEqual({
      ok: true,
      value: [{ index: "p", set: "person", where: [{ attr: "team", op: "=", value: "north" }] }, { index: "d", set: "day" }],
    });
    expect(parseBindings("p in nowhere", CONTEXT, []).ok).toBe(false);
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
        for (const entry of binding.where ?? []) for (const filter of "any" in entry ? entry.any : "index" in entry ? [] : [entry]) add(binding.set, filter.attr);
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
    predictors: (ir.predictors ?? {}) as ModelContext["predictors"],
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

describe("walks along a relationship in equations", () => {
  const ORG: ModelContext = {
    sets: ["employee", "unit"],
    setIds: {},
    attributes: { employee: [{ name: "grade", data_type: "number" }] },
    variables: { pick: { index: ["employee"], domain: "binary" } },
    parameters: {},
    relationships: [
      { name: "manages", from: "employee", to: "employee", attributes: [{ name: "weight", data_type: "number" }] },
      { name: "belongs_to", from: "employee", to: "unit" },
    ],
  };
  const chain: Constraint = {
    id: "c_chain",
    forall: [{ index: "m", set: "employee" }],
    left: {
      sum: { mul: [{ attr: { of: "r", name: "weight", along: "max" } }, { var: "pick", index: ["e"] }] },
      over: [{ index: "e", set: "employee", via: { rel: "manages", from: "m", depth: "any", as: "r" }, where: [{ attr: "grade", op: ">=", value: 2 }] }],
    },
    relation: "<=",
    right: { const: 6 },
  };

  it("writes a recursive walk, its links and a number combined along them, and reads it back exactly", () => {
    const text = ruleEquation(chain, ORG);
    expect(text).toBe("for each m in employee: sum(path_max(weight[r]) * pick[e] for e in employee from m by manages depth any as r where grade >= 2) <= 6");
    const back = parseRule(text!, ORG);
    expect(back.ok && withEquation(chain, back.value)).toEqual(chain);
  });

  it("writes a walk between two sets, and one link's own number", () => {
    const unit: Constraint = {
      id: "c_unit",
      forall: [{ index: "u", set: "unit" }],
      left: { sum: { var: "pick", index: ["e"] }, over: [{ index: "e", set: "employee", via: { rel: "belongs_to", to: "u" } }] },
      relation: ">=",
      right: { const: 1 },
    };
    expect(ruleEquation(unit, ORG)).toBe("for each u in unit: sum(pick[e] for e in employee to u by belongs_to) >= 1");
    const direct: Constraint = {
      id: "c_direct",
      forall: [{ index: "m", set: "employee" }],
      left: { sum: { mul: [{ attr: { of: "r", name: "weight" } }, { var: "pick", index: ["e"] }] }, over: [{ index: "e", set: "employee", via: { rel: "manages", from: "m", as: "r" } }] },
      relation: "<=",
      right: { const: 4 },
    };
    expect(ruleEquation(direct, ORG)).toBe("for each m in employee: sum(weight[r] * pick[e] for e in employee from m by manages as r) <= 4");
  });

  it("says what is wrong with a walk that cannot be taken", () => {
    const message = (text: string) => (parseRule(text, ORG) as { message: string }).message;
    expect(message("sum(pick[e] for e in employee from x by manages) <= 1")).toMatch(/starts at an index bound before it/);
    expect(message("for each m in employee: sum(pick[e] for e in employee from m by reports) <= 1")).toMatch(/“reports” is not a relationship of this model \(manages, belongs_to\)/);
    expect(message("for each m in employee: sum(pick[e] for e in employee from m by belongs_to) <= 1")).toBe("Walking belongs_to from its employee reaches unit, not employee.");
    expect(message("for each m in employee: sum(path_sum(weight[r]) * pick[e] for e in employee from m by manages as r) <= 1")).toMatch(/nothing to combine/);
    expect(message("for each m in employee: sum(pick[r] for e in employee from m by manages as r) <= 1")).toMatch(/names the links of a walk/);
  });
});

describe("walks narrowed four ways, and groups of conditions, in equations", () => {
  const ORG: ModelContext = {
    sets: ["employee"],
    setIds: {},
    attributes: { employee: [{ name: "grade", data_type: "number" }, { name: "band", data_type: "text" }] },
    variables: { pick: { index: ["employee"], domain: "binary" } },
    parameters: {},
    relationships: [{ name: "manages", from: "employee", to: "employee", attributes: [{ name: "weight", data_type: "number" }] }],
  };
  const rule = (over: Binding): Constraint => ({
    id: "c", forall: [{ index: "m", set: "employee" }],
    left: { sum: { var: "pick", index: ["e"] }, over: [over] }, relation: "<=", right: { const: 1 },
  });

  it("writes steps, either way, conditions on the links, a day and an or-group, and reads them back exactly", () => {
    const walk = rule({
      index: "e", set: "employee",
      via: { rel: "manages", both: "m", steps: { min: 2, max: 3 }, where: [{ any: [{ attr: "weight", op: ">", value: 0 }, { attr: "weight", op: "<", value: -5 }] }], on: "2026-10-01" },
      where: [{ any: [{ attr: "band", op: "=", value: "senior" }, { attr: "grade", op: ">=", value: 4 }] }, { attr: "grade", op: "!=", value: 9 }],
    });
    const text = ruleEquation(walk, ORG);
    expect(text).toBe(
      'for each m in employee: sum(pick[e] for e in employee both m by manages steps 2 to 3 through (weight > 0 or weight < -5) on "2026-10-01" ' +
        'where (band = "senior" or grade >= 4) and grade != 9) <= 1',
    );
    const back = parseRule(text!, ORG);
    expect(back.ok && withEquation(walk, back.value)).toEqual(walk);
    expect(ruleEquation(rule({ index: "e", set: "employee", via: { rel: "manages", from: "m", steps: { min: 2 } } }), ORG))
      .toContain("from m by manages steps 2 to any");
  });

  it("says what is wrong with steps, a day or a group", () => {
    const message = (tail: string) => (parseRule(`for each m in employee: sum(pick[e] for e in employee ${tail}) <= 1`, ORG) as { message: string }).message;
    expect(message("from m by manages steps 3 to 2")).toMatch(/whole number no smaller/);
    expect(message("from m by manages on \"tomorrow\"")).toMatch(/YYYY-MM-DD/);
    expect(message("where (grade = 1)")).toMatch(/two or more conditions with or/);
    expect(message("from m by manages through colour = 1")).toMatch(/not an attribute of a manages link \(weight\)/);
  });
});

describe("two items of one set compared (benchmark, October 2026)", () => {
  it("reads and writes 'b > a' as a condition on b, so each pair is taken once", () => {
    const text = "for each a in item, b in item where b > a: x[a] + x[b] <= 1";
    const parsed = parseRule(text, CONTEXT);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.forall).toEqual([{ index: "a", set: "item" }, { index: "b", set: "item", where: [{ index: "a", op: ">" }] }]);
    expect(printRule(parsed.value)).toBe(text);
  });
});

describe("division by a number (benchmark re-test, October 2026)", () => {
  const ctx = { sets: ["item"], setIds: {}, attributes: { item: [{ name: "cost", data_type: "number" }] }, relationships: [],
    variables: { x: { index: ["item"], domain: "integer" } }, parameters: {} } as never;
  it("reads x / 4 as x times a quarter, and refuses a division by a field or by zero", () => {
    const got = parseGoal("sum(x[i] / 4 for i in item)", ctx);
    expect(got.ok && JSON.stringify(got.value)).toContain('"mul":[{"var":"x","index":["i"]},{"const":0.25}]');
    const byField = parseGoal("sum(x[i] / cost[i] for i in item)", ctx);
    expect(!byField.ok && byField.message).toMatch(/Divide by a number here/);
    const byZero = parseGoal("sum(x[i] / 0 for i in item)", ctx);
    expect(!byZero.ok && byZero.message).toBe("Division by zero.");
  });
});

describe("a forecast over decisions (benchmark re-test, October 2026)", () => {
  it("reads predict with a decision as an input inside a sum", () => {
    const ctx = { sets: ["parcel"], setIds: {}, attributes: { parcel: [{ name: "rain", data_type: "number" }] }, relationships: [],
      variables: { water: { index: ["parcel"], domain: "continuous" } }, parameters: {}, predictors: { yield_model: { inputs: 2 } } } as never;
    const got = parseGoal("sum(predict yield_model(water[p], rain[p]) for p in parcel)", ctx);
    expect(got.ok && JSON.stringify(got.value)).toContain('"predict":"yield_model","of":[{"var":"water","index":["p"]}');
  });
});
