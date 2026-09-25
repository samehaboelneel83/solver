import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ACCEPTED_VERSIONS,
  ALL_KEYS,
  ARITHMETIC_ATTR_TYPES,
  DOMAIN_RULES,
  FILTER_OPERATORS,
  IR_RULES,
  IR_VERSION,
  MAX_DEPTH,
  MAX_INDICES,
  MAX_IR_BYTES,
  MAX_TERMS,
  NAME_PATTERN,
  OPTIONAL_KEYS,
  RELATIONS,
  REQUIRED_KEYS,
  SENSES,
  OBJECTIVE_MODES,
  SEVERITIES,
  SHAPE_RULES,
  TERM_KINDS,
  TRAVERSAL_DEPTHS,
  PATH_COMBINATIONS,
  UNCERTAINTY_KINDS,
  FUNCTIONS,
  FUNCTION_CONVEXITIES,
  FUNCTION_DOMAINS,
  FUNCTION_MONOTONICITY,
  VARIABLE_DOMAINS,
  isName,
} from "./contract";

/**
 * The IR contract must not drift between the two languages.
 *
 * Same mechanism as `expressions/parity.test.ts`, and for the same
 * reasons recorded there: the definition is ONE file that the server
 * reads at import time,
 *
 *     backend/app/ir/contract.json
 *
 * and this test reads that file off disk and deep-compares it with
 * `contract.ts`. Generating the TypeScript from the JSON would need Node
 * inside the backend's test container, which it does not have; fetching
 * it from the server would put a round trip in front of an editor that
 * must open instantly.
 *
 * Reading the file from the test rather than from application code is
 * what keeps the bundle unaffected: nothing under `src/` imports across
 * the repository boundary, so Vite never sees this path.
 *
 * The other half of the mechanism is on the server:
 * `test_ir_contract.py` asserts the rule codes are exactly the codes the
 * fixture file exercises, and that every term kind has an implementation.
 * So a rule added here without a fixture fails there, and a rule changed
 * in TypeScript alone fails HERE.
 */

const CONTRACT_PATH = (() => {
  const relative = "backend/app/ir/contract.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) {
      throw new Error(`the IR contract (${relative}) was not found above ${process.cwd()}`);
    }
  }
})();

/** The file, with its `//` commentary dropped -- JSON has no comments, so
 * the contract carries its own as a key no consumer reads. */
function readContract(): Record<string, unknown> {
  const raw = JSON.parse(readFileSync(CONTRACT_PATH, "utf8")) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) if (!key.startsWith("//")) out[key] = value;
  return out;
}

/** The same facts, assembled from the module the browser actually uses. */
function fromTypeScript(): Record<string, unknown> {
  return {
    version: IR_VERSION,
    acceptedVersions: [...ACCEPTED_VERSIONS],
    limits: {
      maxDepth: MAX_DEPTH,
      maxTerms: MAX_TERMS,
      maxIndices: MAX_INDICES,
      maxIrBytes: MAX_IR_BYTES,
    },
    namePattern: NAME_PATTERN,
    topLevel: { required: [...REQUIRED_KEYS], optional: [...OPTIONAL_KEYS] },
    variableDomains: [...VARIABLE_DOMAINS],
    uncertaintyKinds: [...UNCERTAINTY_KINDS],
    functions: FUNCTIONS,
    functionConvexities: [...FUNCTION_CONVEXITIES],
    functionMonotonicity: [...FUNCTION_MONOTONICITY],
    functionDomains: [...FUNCTION_DOMAINS],
    relations: [...RELATIONS],
    severities: [...SEVERITIES],
    senses: [...SENSES],
    objectiveModes: [...OBJECTIVE_MODES],
    termKinds: [...TERM_KINDS],
    traversalDepths: [...TRAVERSAL_DEPTHS],
    pathCombinations: [...PATH_COMBINATIONS],
    filterOperators: [...FILTER_OPERATORS],
    arithmeticAttrTypes: [...ARITHMETIC_ATTR_TYPES],
    rules: IR_RULES.map((rule) => ({ code: rule.code, where: rule.where, text: rule.text })),
  };
}

describe("the IR contract", () => {
  it("is the same in TypeScript and in the JSON the server reads", () => {
    expect(fromTypeScript()).toEqual(readContract());
  });

  // The whole-file assertion above would catch each of these, but it fails
  // with one enormous diff. These name the kinds of drift that have a
  // consequence, so the failure says which one happened.
  it("declares the same rule codes, in the same order", () => {
    const theirs = (readContract().rules as { code: string }[]).map((rule) => rule.code);
    expect(IR_RULES.map((rule) => rule.code)).toEqual(theirs);
  });

  it("agrees on which rules this side can decide", () => {
    const theirs = readContract().rules as { code: string; where: string }[];
    expect([...SHAPE_RULES].sort()).toEqual(
      theirs.filter((r) => r.where === "shape").map((r) => r.code).sort()
    );
    expect([...DOMAIN_RULES].sort()).toEqual(
      theirs.filter((r) => r.where === "domain").map((r) => r.code).sort()
    );
  });

  it("agrees on the version and the four limits", () => {
    const theirs = readContract();
    expect(theirs.version).toBe(IR_VERSION);
    expect(theirs.acceptedVersions).toEqual([...ACCEPTED_VERSIONS]);
    expect(theirs.limits).toEqual({
      maxDepth: MAX_DEPTH,
      maxTerms: MAX_TERMS,
      maxIndices: MAX_INDICES,
      maxIrBytes: MAX_IR_BYTES,
    });
  });

  it("agrees on every closed vocabulary", () => {
    const theirs = readContract();
    expect(theirs.variableDomains).toEqual([...VARIABLE_DOMAINS]);
    expect(theirs.relations).toEqual([...RELATIONS]);
    expect(theirs.severities).toEqual([...SEVERITIES]);
    expect(theirs.senses).toEqual([...SENSES]);
    expect(theirs.objectiveModes).toEqual([...OBJECTIVE_MODES]);
    expect(theirs.termKinds).toEqual([...TERM_KINDS]);
    expect(theirs.traversalDepths).toEqual([...TRAVERSAL_DEPTHS]);
    expect(theirs.pathCombinations).toEqual([...PATH_COMBINATIONS]);
    expect(theirs.filterOperators).toEqual([...FILTER_OPERATORS]);
    expect(theirs.arithmeticAttrTypes).toEqual([...ARITHMETIC_ATTR_TYPES]);
  });

  it("agrees on the top-level keys", () => {
    const theirs = readContract().topLevel as { required: string[]; optional: string[] };
    expect([...REQUIRED_KEYS]).toEqual(theirs.required);
    expect([...OPTIONAL_KEYS]).toEqual(theirs.optional);
    expect([...ALL_KEYS].sort()).toEqual([...theirs.required, ...theirs.optional].sort());
  });

  it("narrows the filter operators to ones the expression catalogue has", () => {
    // The whole reason a model's filters were not given a table of their
    // own. The server raises at import time if this is false; here it is
    // a test, so the failure says which name is the problem.
    const catalogue = JSON.parse(
      readFileSync(
        resolve(dirname(CONTRACT_PATH), "..", "expressions", "catalogue.json"),
        "utf8"
      )
    ) as { operators: Record<string, unknown> };
    for (const operator of FILTER_OPERATORS) {
      expect(Object.keys(catalogue.operators), operator).toContain(operator);
    }
  });
});

describe("the name rule", () => {
  // Python's `$` also matches just before a trailing newline and
  // JavaScript's does not, which is why the server uses `re.fullmatch` on
  // an unanchored body. Both ends have to agree, or a name would pass one
  // validator and be refused by Postgres.
  it.each(["employee", "day", "a", "hours_per_week", "x1"])("accepts %s", (name) => {
    expect(isName(name)).toBe(true);
  });

  it.each(["Employee", "1day", "_x", "", "day ", "day\n", "day-shift", "día"])(
    "refuses %j",
    (name) => {
      expect(isName(name)).toBe(false);
    }
  );
});
