import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { EXPRESSION_VERSION } from "./document";
import { ENTITY_COLUMNS, RELATIONSHIP_DIRECTIONS } from "./fields";
import { EXPRESSION_FUNCTIONS } from "./functions";
import { EXPRESSION_OPERATORS, NULL_OPERATORS, OPERATORS_BY_TYPE } from "./operators";
import { MAX_DEPTH, MAX_LIST_LENGTH, MAX_RULES } from "./validate";

/**
 * The catalogue must not drift between the two languages.
 *
 * Task 14c owns the catalogue as TypeScript, because the builder needs the
 * types and the bundler needs to tree-shake it. Task 14d's SQL compiler is
 * Python and cannot read TypeScript, so the shared facts -- the version,
 * the limits, the entity columns, the operator table, which operators each
 * data type offers, and the ten functions -- live in ONE file that the
 * server reads at import time:
 *
 *     backend/app/expressions/catalogue.json
 *
 * and this test deep-compares that file against the TypeScript modules.
 *
 * Why this mechanism and not the other two the brief offered:
 *
 * - "generate the JSON from the TypeScript" would need Node inside the
 *   backend's test container to verify, and it has none -- the check would
 *   degrade to a skip, and a parity test that skips is not a parity test.
 * - "make the server authoritative and have the client fetch it" would put
 *   a network round trip in front of a builder that must open instantly and
 *   work with a cached page, and would make the offline behaviour of the
 *   Entities page depend on a second request.
 *
 * Reading the file from the test (not from application code) is what keeps
 * the bundle unaffected: nothing under `src/` imports across the repo
 * boundary, so Vite never sees this path. Vitest runs in Node, so
 * `node:fs` is available even under the jsdom environment.
 *
 * The other half of the mechanism is on the server: a pytest asserts that
 * the set of function names in this file is exactly the set the compiler
 * has a builder for. So an entry added here without an implementation
 * fails there, an entry implemented without being declared here fails
 * there, and an entry changed in TypeScript alone fails HERE.
 */

/** Walked up from the working directory rather than resolved against
 * `import.meta.url`: vitest transforms this module, so `import.meta.url` is
 * not a `file:` URL here. Walking also means the test still finds the file
 * if it is ever run from the repository root instead of `frontend/`. */
const CATALOGUE_PATH = (() => {
  const relative = "backend/app/expressions/catalogue.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) {
      throw new Error(`the shared catalogue (${relative}) was not found above ${process.cwd()}`);
    }
  }
})();

/** The file, with its `//` commentary dropped -- JSON has no comments, so
 * the catalogue carries its own as a key no consumer reads. */
function readCatalogue(): Record<string, unknown> {
  const raw = JSON.parse(readFileSync(CATALOGUE_PATH, "utf8")) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) if (!key.startsWith("//")) out[key] = value;
  return out;
}

/** The same facts, assembled from the modules the browser actually uses. */
function fromTypeScript(): Record<string, unknown> {
  return {
    version: EXPRESSION_VERSION,
    limits: { maxDepth: MAX_DEPTH, maxRules: MAX_RULES, maxListLength: MAX_LIST_LENGTH },
    relationshipDirections: [...RELATIONSHIP_DIRECTIONS],
    columns: ENTITY_COLUMNS.map((c) => ({
      column: c.column,
      label: c.label,
      dataType: c.dataType,
      nullable: c.nullable,
    })),
    operators: Object.fromEntries(
      Object.entries(EXPRESSION_OPERATORS).map(([name, def]) => [
        name,
        { name: def.name, label: def.label, arity: def.arity },
      ])
    ),
    operatorsByType: Object.fromEntries(
      Object.entries(OPERATORS_BY_TYPE).map(([type, names]) => [type, [...names]])
    ),
    nullOperators: [...NULL_OPERATORS],
    functions: Object.fromEntries(
      Object.entries(EXPRESSION_FUNCTIONS).map(([name, def]) => [
        name,
        {
          name: def.name,
          argument: def.argument,
          argumentTypes: [...def.argumentTypes],
          returns: def.returns,
          description: def.description,
          sql: def.sql,
        },
      ])
    ),
  };
}

describe("the shared catalogue", () => {
  it("is the same in TypeScript and in the JSON the server reads", () => {
    expect(fromTypeScript()).toEqual(readCatalogue());
  });

  // The whole-file assertion above would catch each of these, but it fails
  // with one enormous diff. These name the four kinds of drift that have a
  // consequence, so the failure says which one happened.
  it("declares the same function names on both sides", () => {
    expect(Object.keys(EXPRESSION_FUNCTIONS).sort()).toEqual(
      Object.keys(readCatalogue().functions as object).sort()
    );
  });

  it("declares the same operator names on both sides", () => {
    expect(Object.keys(EXPRESSION_OPERATORS).sort()).toEqual(
      Object.keys(readCatalogue().operators as object).sort()
    );
  });

  it("gives each function the same argument and return types on both sides", () => {
    const theirs = readCatalogue().functions as Record<string, { argumentTypes: string[]; returns: string }>;
    for (const [name, def] of Object.entries(EXPRESSION_FUNCTIONS)) {
      expect([...def.argumentTypes], name).toEqual(theirs[name]?.argumentTypes);
      expect(def.returns, name).toEqual(theirs[name]?.returns);
    }
  });

  it("agrees on the version and the three limits", () => {
    const theirs = readCatalogue();
    expect(theirs.version).toBe(EXPRESSION_VERSION);
    expect(theirs.limits).toEqual({
      maxDepth: MAX_DEPTH,
      maxRules: MAX_RULES,
      maxListLength: MAX_LIST_LENGTH,
    });
  });
});
