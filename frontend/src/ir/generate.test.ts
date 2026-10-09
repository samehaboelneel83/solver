import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parts } from "./generate";
import { checkIrShape } from "./validate";

/** Generated sets (plan 1B): the recipe checks, from the fixture `backend/tests/test_generate.py` reads too. */
const FIXTURE_PATH = (() => {
  const relative = "backend/tests/generate_fixtures.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

type Case = { why: string; change: Record<string, unknown>; code: string; loc: (string | number)[] };
const FIXTURES = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as { base: Record<string, unknown>; invalid: Case[] };

describe("generated sets in a model", () => {
  it("accepts a model over sets its recipes make", () => {
    expect(checkIrShape(FIXTURES.base)).toBeNull();
  });

  it.each(FIXTURES.invalid.map((c) => [c.why, c] as const))("refuses %s", (_why, c) => {
    const problem = checkIrShape({ ...FIXTURES.base, ...c.change });
    expect(problem && { code: problem.code, loc: problem.loc }).toEqual({ code: c.code, loc: c.loc });
  });

  it("names a set's parts as the server does", () => {
    expect(parts(["cell", "cell", "ward"])).toEqual(["cell", "cell_2", "ward"]);
  });
});
