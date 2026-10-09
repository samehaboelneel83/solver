/**
 * `generate` (version 2, plan phase 1B): sets the worker builds from a recipe instead of stored records.
 * The same checks, in the same order and with the same codes, as `check` and `outputs` in
 * `backend/app/solve/generate.py`; the building itself is only there.
 */

type Json = Record<string, unknown>;

export const RECIPE_KINDS = ["range", "product", "positions"] as const;
const KEYS: Record<string, [string[], string[]]> = {
  range: [["kind", "set", "from", "to", "step"], ["kind", "set", "from", "to"]],
  product: [["kind", "set", "of", "linked", "same", "distinct", "unordered"], ["kind", "set", "of"]],
  positions: [
    ["kind", "areas", "shape", "kinds", "length", "width", "can_turn", "value", "step", "origin", "aisle",
      "aisle_sides", "access", "access_shape", "items", "cells", "occupies", "keeps_free", "next_to"],
    ["kind", "areas", "shape", "kinds", "length", "width", "step", "origin", "items", "cells", "occupies"],
  ],
};
const AISLE_SIDES = ["long", "short", "any"];
const NAME = /^[a-z][a-z0-9_]*$/;

const isName = (value: unknown): value is string => typeof value === "string" && NAME.test(value);
const isInt = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value);
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const sorted = (values: Iterable<string>) => [...values].sort();
/** Python's repr of a string, as the server's messages show names. */
const repr = (value: unknown) => (typeof value === "string" ? `'${value}'` : JSON.stringify(value));

/** Each part's attribute name: the set's name, then "<set>_2", "<set>_3" for a set named again. */
export function parts(of: string[]): string[] {
  const seen = new Map<string, number>();
  return of.map((name) => {
    const n = (seen.get(name) ?? 0) + 1;
    seen.set(name, n);
    return n === 1 ? name : `${name}_${n}`;
  });
}

/** What a (shape-valid) recipe makes: its sets and its relationships. */
export function outputs(recipe: Json): { sets: string[]; relationships: string[] } {
  if (recipe.kind === "range") return { sets: [recipe.set as string], relationships: [] };
  if (recipe.kind === "product") {
    const name = recipe.set as string;
    return { sets: [name], relationships: parts(recipe.of as string[]).map((p) => `${name}_${p}`) };
  }
  const relationships = [recipe.occupies as string];
  if (recipe.keeps_free) relationships.push(recipe.keeps_free as string);
  if (recipe.next_to) relationships.push(recipe.next_to as string);
  return { sets: [recipe.items as string, recipe.cells as string], relationships };
}

export type RecipeFault = [code: string, loc: (string | number)[], message: string];

/** The first fault of one recipe, given the sets and relationships known before it. */
export function checkRecipe(recipe: unknown, sets: Set<string>, relationships: Set<string>): RecipeFault | null {
  if (typeof recipe !== "object" || recipe === null || Array.isArray(recipe)
      || !RECIPE_KINDS.includes((recipe as Json).kind as never)) {
    return ["generate_malformed", ["kind"], `a recipe is an object whose kind is one of ${RECIPE_KINDS.join(", ")}`];
  }
  const r = recipe as Json;
  const kind = r.kind as string;
  const [allowed, required] = KEYS[kind];
  for (const key of sorted(Object.keys(r))) {
    if (!allowed.includes(key)) {
      return ["generate_malformed", [key], `a ${kind} recipe reads ${sorted(allowed).join(", ")}; not ${repr(key)}`];
    }
  }
  for (const key of sorted(required)) {
    if (!(key in r)) return ["generate_malformed", [key], `a ${kind} recipe needs ${key}`];
  }
  const knownSet = (key: string, value: unknown): RecipeFault | null => {
    if (!isName(value)) return ["generate_malformed", [key], `${key} is a set's name`];
    if (!sets.has(value)) {
      return ["generate_unknown_set", [key],
        `${repr(value)} is not a set of this model (list it in sets, or make it in an earlier recipe)`];
    }
    return null;
  };
  const attrName = (key: string): RecipeFault | null =>
    typeof r[key] === "string" && r[key] !== "" ? null : ["generate_malformed", [key], `${key} is an attribute's name`];

  let made: unknown[];
  if (kind === "range") {
    const step = "step" in r ? r.step : 1;
    if (![r.from, r.to, step].every(isInt) || (step as number) <= 0) {
      return ["generate_malformed", ["step"], "from, to and step are whole numbers, step above 0"];
    }
    if ((r.to as number) < (r.from as number)) return ["generate_malformed", ["to"], "to is at least from"];
    made = [r.set];
  } else if (kind === "product") {
    const of = r.of;
    if (!Array.isArray(of) || of.length < 2 || of.length > 4) {
      return ["generate_malformed", ["of"], "of names two to four sets"];
    }
    for (let i = 0; i < of.length; i += 1) {
      const problem = knownSet("of", of[i]);
      if (problem) return [problem[0], ["of", i], problem[2]];
    }
    if ("linked" in r && (!isName(r.linked) || !relationships.has(r.linked))) {
      return ["generate_unknown_relationship", ["linked"],
        `${repr(r.linked)} is not a relationship of this model (list it in relationships)`];
    }
    const same = "same" in r ? r.same : [];
    if (!Array.isArray(same) || !same.every((p) => Array.isArray(p) && p.length === 2
        && p.every((a) => typeof a === "string" && a !== ""))) {
      return ["generate_malformed", ["same"],
        'same is a list of [attribute of the first, attribute of the second] pairs, e.g. [["ward", "ward"]]'];
    }
    for (const key of ["distinct", "unordered"]) {
      if (key in r && typeof r[key] !== "boolean") return ["generate_malformed", [key], `${key} is true or false`];
    }
    made = [r.set];
  } else {
    for (const key of ["areas", "kinds", ...("access" in r ? ["access"] : [])]) {
      const problem = knownSet(key, r[key]);
      if (problem) return problem;
    }
    for (const key of ["shape", "length", "width", ...["can_turn", "value", "access_shape"].filter((k) => k in r)]) {
      const problem = attrName(key);
      if (problem) return problem;
    }
    if ("access" in r && !("access_shape" in r)) {
      return ["generate_malformed", ["access_shape"], "access needs access_shape: its features' WKT attribute"];
    }
    if (!isNumber(r.step) || !(r.step > 0)) {
      return ["generate_malformed", ["step"], "step is the grid's step in metres, above 0"];
    }
    if (!Array.isArray(r.origin) || r.origin.length !== 2 || !r.origin.every(isNumber)) {
      return ["generate_malformed", ["origin"], "origin is [x, y] in metres"];
    }
    const aisle = "aisle" in r ? r.aisle : 0;
    if (!isInt(aisle) || aisle < 0) {
      return ["generate_malformed", ["aisle"], "aisle is a whole number of cells, 0 or more"];
    }
    if (aisle && !AISLE_SIDES.includes((r.aisle_sides ?? "long") as string)) {
      return ["generate_malformed", ["aisle_sides"], `aisle_sides is one of ${AISLE_SIDES.join(", ")}`];
    }
    if (aisle && !r.keeps_free) {
      return ["generate_malformed", ["keeps_free"], "an aisle needs keeps_free: the name of its links"];
    }
    if ("access" in r && !r.next_to) {
      return ["generate_malformed", ["next_to"], "access needs next_to: the name of the links between cells"];
    }
    made = [r.items, r.cells];
    for (const key of ["items", "cells", "occupies", "keeps_free", "next_to"]) {
      if (key in r && !isName(r[key])) return ["generate_malformed", [key], `${key} is a name: ^[a-z][a-z0-9_]*$`];
    }
    if (r.items === r.cells) return ["generate_malformed", ["cells"], "items and cells are two sets"];
  }
  if (!made.every(isName)) return ["generate_malformed", ["set"], "set is a name: ^[a-z][a-z0-9_]*$"];
  const out = outputs(r);
  for (const name of out.sets) {
    if (sets.has(name) || relationships.has(name)) {
      const loc = kind !== "positions" ? "set" : name === r.items ? "items" : "cells";
      return ["generate_name_taken", [loc], `${repr(name)} is already a set or relationship of this model`];
    }
  }
  const names = out.relationships;
  if (new Set(names).size !== names.length || names.some((n) => out.sets.includes(n))) {
    return ["generate_name_taken", [], "a recipe's links and sets each need their own name"];
  }
  for (const name of names) {
    if (sets.has(name) || relationships.has(name)) {
      return ["generate_name_taken", [], `${repr(name)} is already a set or relationship of this model`];
    }
  }
  return null;
}

function recipesOf(ir: Json): Json[] {
  const recipes = ir.generate;
  if (!Array.isArray(recipes)) return [];
  return recipes.filter((r): r is Json => typeof r === "object" && r !== null && !Array.isArray(r)
    && RECIPE_KINDS.includes((r as Json).kind as never));
}

/** The sets a model's recipes make: not declared in `sets`, but rules may range over them like any. */
export function generatedSets(ir: Json): string[] {
  return recipesOf(ir).flatMap((r) => {
    try {
      return outputs(r).sets.filter((name) => typeof name === "string");
    } catch {
      return [];
    }
  });
}

/**
 * The relationships a model declares, given the ones its rules walk: less the ones its recipes make (they are
 * built by the run, never frozen -- declaring one is `generate_name_taken`), plus the ones its recipes read (a
 * product's `linked`, which no rule need walk). Both editors derive `relationships` through this.
 */
export function relationshipsToDeclare(ir: Json, walked: Iterable<string>): string[] {
  const made = new Set<string>();
  const read: string[] = [];
  for (const recipe of recipesOf(ir)) {
    try {
      outputs(recipe).relationships.forEach((name) => made.add(name));
    } catch {
      // A malformed recipe makes nothing the editor can name; the validator says what is wrong with it.
    }
    if (recipe.kind === "product" && typeof recipe.linked === "string") read.push(recipe.linked);
  }
  const out = [...walked].filter((name) => !made.has(name));
  for (const name of read) if (!out.includes(name)) out.push(name);
  return out;
}
