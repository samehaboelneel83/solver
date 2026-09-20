import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DOMAIN_RULES, MAX_DEPTH, MAX_TERMS, SHAPE_RULES } from "./contract";
import { checkIrShape, isValidIrShape } from "./validate";

/**
 * The browser half of the IR fixture set.
 *
 * `backend/tests/ir_fixtures.json` carries eight valid IRs and one
 * invalid one per rule, each wrong in exactly one way.
 * `backend/tests/test_ir_validate.py` runs them through
 * `app/ir/validate.py`; this file runs them through `validate.ts`.
 *
 * **Both assert the `code` and `loc` in the file, never each other's
 * output.** Two implementations that agree with each other and disagree
 * with the contract would prove nothing, so the answers were derived by
 * hand from `docs/contracts/problem-ir.md` and pinned in the fixture next
 * to the reasoning, exactly as `expression_cross_check.json` already does
 * for the expression core.
 *
 * The cases whose rule is `where: domain` cannot be decided here at all
 * -- they ask what entity types and attributes a domain declares. They
 * are asserted to be *accepted* by this validator, and counted: a rule
 * that silently moved from `domain` to `shape` would make one of those
 * assertions fail rather than quietly stop being checked.
 */

const FIXTURE_PATH = (() => {
  const relative = "backend/tests/ir_fixtures.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

type Generate = { kind: "nestedAdd" | "wideAdd" | "padNote"; count: number };
type Fixture = {
  valid: { name: string; why: string; ir: unknown }[];
  invalid: {
    code: string;
    loc: (string | number)[];
    why: string;
    ir?: unknown;
    generate?: Generate;
  }[];
};

const FIXTURES = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as Fixture;

/** The three limit cases. Kept identical to `build_generated` in
 * `backend/tests/test_ir_validate.py`; an IR large enough to break a
 * limit is not worth five hundred hand-written lines, and the shape it
 * takes is still written down -- here and there. */
function buildGenerated(spec: Generate): unknown {
  let term: unknown;
  let note: string | null = null;
  if (spec.kind === "nestedAdd") {
    term = { const: 1 };
    for (let i = 0; i < spec.count; i += 1) term = { add: [term] };
  } else if (spec.kind === "wideAdd") {
    term = { add: Array.from({ length: spec.count }, () => ({ const: 1 })) };
  } else {
    term = { const: 0 };
    note = "x".repeat(spec.count);
  }
  const constraint: Record<string, unknown> = {
    id: "c_one",
    left: term,
    relation: "<=",
    right: { const: 1 },
    severity: "hard",
  };
  if (note !== null) constraint.note = note;
  return {
    version: 1,
    sets: [],
    parameters: {},
    variables: { x: { index: [], domain: "binary" } },
    constraints: [constraint],
  };
}

function caseIr(entry: Fixture["invalid"][number]): unknown {
  return entry.generate ? buildGenerated(entry.generate) : entry.ir;
}

const SHAPE_CASES = FIXTURES.invalid.filter((entry) => SHAPE_RULES.has(entry.code));
const DOMAIN_CASES = FIXTURES.invalid.filter((entry) => DOMAIN_RULES.has(entry.code));

describe("valid IRs", () => {
  it.each(FIXTURES.valid.map((entry) => [entry.name, entry] as const))(
    "%s is accepted",
    (_name, entry) => {
      expect(checkIrShape(entry.ir)).toBeNull();
    }
  );

  it("includes the seeded workforce model, expressed rather than named", () => {
    const workforce = FIXTURES.valid.find((entry) => entry.name === "workforce");
    expect(workforce).toBeDefined();
    const ir = workforce!.ir as { constraints: { left?: unknown; relation?: unknown }[] };
    expect(ir.constraints).toHaveLength(3);
    // The sketch this replaced had an id and a note and nothing else.
    for (const constraint of ir.constraints) {
      expect(constraint.left).toBeDefined();
      expect(constraint.relation).toBeDefined();
    }
  });
});

describe("invalid IRs, one rule at a time", () => {
  it.each(SHAPE_CASES.map((entry) => [entry.code, entry] as const))(
    "%s is refused with its loc",
    (_code, entry) => {
      const refusal = checkIrShape(caseIr(entry));
      expect(refusal, entry.why).not.toBeNull();
      expect(refusal!.code).toBe(entry.code);
      expect(refusal!.loc).toEqual(entry.loc);
      expect(refusal!.message.trim().length).toBeGreaterThan(0);
    }
  );

  it.each(DOMAIN_CASES.map((entry) => [entry.code, entry] as const))(
    "%s is a domain rule, so this half accepts it",
    (_code, entry) => {
      // Single fault, from this side: the document is shape-valid, which
      // is what leaves the server's domain half the only thing that can
      // refuse it.
      expect(checkIrShape(caseIr(entry))).toBeNull();
    }
  );

  it("checks every rule the contract says this side can decide", () => {
    expect(new Set(SHAPE_CASES.map((entry) => entry.code))).toEqual(SHAPE_RULES);
  });

  it("leaves exactly the rules that need rows to the server", () => {
    expect(new Set(DOMAIN_CASES.map((entry) => entry.code))).toEqual(DOMAIN_RULES);
    expect(DOMAIN_CASES.length).toBeGreaterThan(0);
  });
});

describe("the limits", () => {
  it("accepts a document one nesting inside the depth limit", () => {
    expect(isValidIrShape(buildGenerated({ kind: "nestedAdd", count: MAX_DEPTH - 1 }))).toBe(true);
  });

  it("accepts a document with exactly the term limit", () => {
    // The `add` is a term and so is the constraint's `right`, so
    // MAX_TERMS - 2 summands make exactly MAX_TERMS.
    expect(isValidIrShape(buildGenerated({ kind: "wideAdd", count: MAX_TERMS - 2 }))).toBe(true);
  });

  it("measures the byte limit in bytes, not in characters", () => {
    // A JavaScript string's `length` counts UTF-16 code units; the server
    // counts UTF-8 bytes. A note of multi-byte characters is where the
    // two answers would differ, and the two validators have to agree on
    // which side of the limit a document is.
    const almost = buildGenerated({ kind: "padNote", count: 1 }) as {
      constraints: { note: string }[];
    };
    almost.constraints[0].note = "é".repeat(200_000);
    const refusal = checkIrShape(almost);
    expect(refusal?.code).toBe("ir_too_large");
    expect(refusal?.message).toMatch(/4\d{5} bytes/);
  });
});
