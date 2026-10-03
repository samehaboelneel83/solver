/**
 * The shape half of the problem IR contract, in the browser.
 *
 * This is the client's copy of `backend/app/ir/validate.py`'s
 * `check_shape`, and it exists for the same reason `validate.ts` exists
 * beside the expression compiler: a model editor has to be able to say
 * what is wrong before it sends anything, and every rule marked `shape`
 * in `contract.json` is one that needs no database to decide.
 *
 * **It returns ONE refusal, not all of them**, and the order the rules
 * are applied in is part of the contract -- the server returns the same
 * one, and `backend/tests/ir_fixtures.json` pins the pair for every rule
 * by being single-fault. The two implementations are laid out in the same
 * order, function for function, so a divergence is visible in a diff and
 * not only in a failing test.
 *
 * The rules marked `domain` are not here and cannot be: they ask what
 * entity types, attributes and parameters a domain declares.
 */

import {
  ALL_KEYS,
  EDGE_MARK,
  PATH_COMBINATIONS,
  CONSTRAINT_KEYS,
  INTERVAL_KEYS,
  UNCERTAINTY_KINDS,
  SCHEDULING_KEYS,
  CONNECTED_KEYS,
  ROUTE_KEYS,
  FILTER_OPERATORS,
  FUNCTIONS,
  ACCEPTED_VERSIONS,
  IR_VERSION,
  MAX_DEPTH,
  MAX_INDICES,
  MAX_IR_BYTES,
  MAX_TERMS,
  RELATIONS,
  REQUIRED_KEYS,
  SENSES,
  OBJECTIVE_MODES,
  SEVERITIES,
  TERM_KINDS,
  TRAVERSAL_DEPTHS,
  VARIABLE_DOMAINS,
  isName,
} from "./contract";

export type IrLoc = (string | number)[];

/** One reason an IR is not a model. `loc` is the path INSIDE the ir, so
 * a route can prefix `["body", "ir"]` and a builder can highlight what it
 * names (Ruling 30). */
export type IrRefusal = { code: string; loc: IrLoc; message: string };

type Json = Record<string, unknown>;

const LIST_OPERATORS: ReadonlySet<string> = new Set(["in", "notIn"]);
const BINDING_KEYS: ReadonlySet<string> = new Set(["index", "set", "where", "via"]);
/**
 * A `via` names the relationship, where the *anchor* sits, and how far to
 * walk. `from` and `to` are the anchor's end, so the index being bound takes
 * the other one -- which is why exactly one of them appears and neither is
 * the new index's own name.
 */
const VIA_KEYS: ReadonlySet<string> = new Set(["rel", "from", "to", "both", "depth", "steps", "where", "on", "as"]);
const VIA_ENDS = ["from", "to", "both"] as const;
const STEPS_KEYS: ReadonlySet<string> = new Set(["min", "max"]);

/** Whether a walk takes exactly one step, so a link it names is one link rather than a path. */
function singleStep(via: Json): boolean {
  const steps = via.steps;
  if (isObject(steps)) return steps.min === 1 && steps.max === 1;
  return (via.depth ?? "one") === "one";
}

function isDate(value: unknown): boolean {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** A scope entry that is an edge a `via` names (queue R19), not a set. */
const isEdge = (bound: string | undefined): boolean => typeof bound === "string" && bound.startsWith(EDGE_MARK);
const FILTER_KEYS: ReadonlySet<string> = new Set(["attr", "op", "value"]);
const INDEX_OPERATORS = ["=", "!=", "<", "<=", ">", ">="];
const VARIABLE_KEYS: ReadonlySet<string> = new Set(["index", "domain", "lower", "upper", "stage", ...INTERVAL_KEYS]);
const PARAMETER_KEYS: ReadonlySet<string> = new Set(["index", "uncertainty", "entity"]);
const OBJECTIVE_KEYS: ReadonlySet<string> = new Set(["sense", "terms", "mode"]);
const OBJECTIVE_TERM_KEYS: ReadonlySet<string> = new Set(["id", "weight", "expression"]);
/** A predictor takes at most this many inputs (`app.ml.trees.MAX_INPUTS`). */
const MAX_PREDICTOR_INPUTS = 32;
const TERM_KEYS: Record<string, readonly string[]> = {
  const: [],
  par: ["index"],
  var: ["index"],
  attr: [],
  sum: ["over"],
  add: [],
  mul: [],
  pwl: ["points"],
  fn: ["of"],
  predict: ["of"],
};

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** JSON has one number type, so "an integer" is a value check, not a type
 * check. `true` is not a quantity -- the Python side gets the same rule
 * from `bool` subclassing `int`. */
function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

/** A number, but not a boolean and not an IEEE special. JSON cannot carry a
 * NaN or an infinity, but a hand-built document can, and a coefficient of
 * infinity is a model no solver answers usefully. */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isScalar(value: unknown): boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function show(value: unknown): string {
  return JSON.stringify(value) ?? String(value);
}

function refusal(code: string, loc: IrLoc, message: string): IrRefusal {
  return { code, loc, message };
}

function unknownKey(
  node: Json,
  allowed: ReadonlySet<string>,
  loc: IrLoc,
  what: string
): IrRefusal | null {
  for (const key of Object.keys(node)) {
    if (!allowed.has(key)) {
      return refusal(
        "key_unknown",
        [...loc, key],
        `${show(key)} is not a key a ${what} carries; this version reads ${[...allowed]
          .sort()
          .join(", ")}`
      );
    }
  }
  return null;
}

class ShapeChecker {
  readonly sets = new Set<string>();
  readonly relationships = new Set<string>();
  readonly parameters = new Map<string, string[]>();
  /** Queue R20b: parameter name -> the set its values are entities of. */
  readonly entityParameters = new Map<string, string>();
  readonly variables = new Map<string, string[]>();
  /** Epic ML: predictor name -> how many inputs the model declares it takes. */
  readonly predictors = new Map<string, number>();
  terms = 0;

  constructor(private readonly ir: Json) {}

  checkSets(): IrRefusal | null {
    const sets = this.ir.sets;
    if (!Array.isArray(sets)) {
      return refusal(
        "sets_not_array",
        ["sets"],
        "sets must be an array of entity type names: snapshot_dataset() reads it with " +
          "jsonb_array_elements_text and anything else reaches it as an error"
      );
    }
    for (let i = 0; i < sets.length; i += 1) {
      const name = sets[i];
      if (!isName(name)) {
        return refusal(
          "set_not_a_name",
          ["sets", i],
          `${show(name)} is not an entity type name; entity_type.name is ^[a-z][a-z0-9_]*$`
        );
      }
      if (this.sets.has(name)) {
        return refusal("set_duplicated", ["sets", i], `the set '${name}' is named twice`);
      }
      this.sets.add(name);
    }
    return null;
  }

  /**
   * `relationships` declares which edge types the dataset must freeze.
   *
   * Optional, and absent means none -- which is every model written before
   * traversal existed. It mirrors `sets` exactly, and for the same reason:
   * `snapshot_dataset()` freezes what this names and nothing else, so a
   * `via` that walked an undeclared type would reference data the frozen
   * document does not carry.
   */
  checkRelationships(): IrRefusal | null {
    const relationships = this.ir.relationships;
    if (relationships === undefined) return null;
    if (!Array.isArray(relationships)) {
      return refusal(
        "relationships_not_array",
        ["relationships"],
        "relationships must be an array of relationship type names; omit the key entirely " +
          "for a model that does not traverse"
      );
    }
    for (let i = 0; i < relationships.length; i += 1) {
      const name = relationships[i];
      if (!isName(name)) {
        return refusal(
          "relationship_not_a_name",
          ["relationships", i],
          `${show(name)} is not a relationship type name; relationship_type.name is ` +
            "^[a-z][a-z0-9_]*$"
        );
      }
      if (this.relationships.has(name)) {
        return refusal(
          "relationship_duplicated",
          ["relationships", i],
          `the relationship '${name}' is named twice`
        );
      }
      this.relationships.add(name);
    }
    return null;
  }

  checkParameters(): IrRefusal | null {
    const parameters = this.ir.parameters;
    if (!isObject(parameters)) {
      return refusal(
        "parameters_not_object",
        ["parameters"],
        "parameters must be an object keyed by parameter name: snapshot_dataset() reads it " +
          "with jsonb_object_keys"
      );
    }
    for (const [name, declaration] of Object.entries(parameters)) {
      const at: IrLoc = ["parameters", name];
      if (!isName(name)) {
        return refusal(
          "parameter_not_a_name",
          at,
          `${show(name)} is not a parameter name; parameter_def.name is ^[a-z][a-z0-9_]*$`
        );
      }
      if (!isObject(declaration)) {
        return refusal(
          "parameter_not_object",
          at,
          `the declaration of '${name}' must be an object carrying its index`
        );
      }
      const problem = unknownKey(declaration, PARAMETER_KEYS, at, "parameter declaration");
      if (problem) return problem;
      const index = declaration.index;
      if (
        !Array.isArray(index) ||
        // Empty is one number (migration 0104).
        index.length > MAX_INDICES ||
        !index.every((s) => typeof s === "string")
      ) {
        return refusal(
          "parameter_index_not_array",
          [...at, "index"],
          `'${name}' must declare index as an array of 0 to ${MAX_INDICES} set names, in the ` +
            "order parameter_def.index_type_ids holds them"
        );
      }
      for (let j = 0; j < index.length; j += 1) {
        if (!this.sets.has(index[j] as string)) {
          return refusal(
            "parameter_index_not_declared",
            [...at, "index", j],
            `'${name}' is indexed by ${show(index[j])}, which this model does not declare in ` +
              "sets, so no dataset would carry it"
          );
        }
      }
      const uncertainty = this.checkUncertainty(name, declaration, at);
      if (uncertainty) return uncertainty;
      if ("entity" in declaration) {
        const of = declaration.entity;
        const v1 = this.ir.version === 1;
        if (v1 || typeof of !== "string" || !this.sets.has(of) || "uncertainty" in declaration) {
          return refusal(
            "parameter_entity_invalid",
            [...at, "entity"],
            `'${name}''s values are entities of ${show(of)}, which ` +
              (v1 ? "needs version 2" : "uncertainty" in declaration ? "has no uncertainty" : "this model does not declare in sets")
          );
        }
        this.entityParameters.set(name, of);
      }
      this.parameters.set(name, index as string[]);
    }
    return null;
  }

  /** `_check_uncertainty` in `app/ir/validate.py`, in the same order. */
  private checkUncertainty(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
    if (!("uncertainty" in declaration)) return null;
    const loc: IrLoc = [...at, "uncertainty"];
    if (this.ir.version === 1) {
      return refusal(
        "uncertainty_needs_version_2",
        loc,
        `'${name}' declares an uncertainty, which version 1 does not have; publish it as version 2`
      );
    }
    const spec = declaration.uncertainty;
    const kind = isObject(spec) ? spec.kind : undefined;
    if (!(UNCERTAINTY_KINDS as readonly unknown[]).includes(kind)) {
      return refusal(
        "uncertainty_malformed",
        loc,
        `an uncertainty names its kind: ${[...UNCERTAINTY_KINDS].sort().join(" or ")}`
      );
    }
    const body = spec as Json;
    const allowed = kind === "interval" ? ["kind", "deviation", "gamma"] : ["kind", "futures"];
    const extra = Object.keys(body).filter((key) => !allowed.includes(key)).sort();
    if (extra.length > 0) {
      return refusal("uncertainty_malformed", [...loc, extra[0]], `a ${String(kind)} uncertainty carries no ${extra[0]}`);
    }
    if (kind === "scenarios") {
      const futures = body.futures;
      if (!Array.isArray(futures) || futures.length === 0) {
        return refusal(
          "uncertainty_malformed",
          [...loc, "futures"],
          `'${name}' varies by scenario, so it lists at least one future with a positive factor (and an optional label)`
        );
      }
      for (let i = 0; i < futures.length; i++) {
        const row = futures[i];
        const rowLoc: IrLoc = [...loc, "futures", i];
        if (!isObject(row)) {
          return refusal("uncertainty_malformed", rowLoc, `'${name}'s future ${i + 1} is an object with factor`);
        }
        const stray = Object.keys(row).filter((key) => key !== "label" && key !== "factor").sort();
        if (stray.length > 0) {
          return refusal("uncertainty_malformed", [...rowLoc, stray[0]], `a scenario future carries no ${stray[0]}`);
        }
        const factor = row.factor;
        if (typeof factor !== "number" || !Number.isFinite(factor) || !(factor > 0)) {
          return refusal(
            "uncertainty_malformed",
            [...rowLoc, "factor"],
            `'${name}'s future ${i + 1} needs a positive factor (1 keeps the stored value, 1.2 is twenty per cent higher)`
          );
        }
        if ("label" in row && (typeof row.label !== "string" || !String(row.label).trim())) {
          return refusal(
            "uncertainty_malformed",
            [...rowLoc, "label"],
            `'${name}'s future ${i + 1} label is non-empty text when given`
          );
        }
      }
      return null;
    }
    if (kind === "interval") {
      for (const key of ["deviation", "gamma"]) {
        if (!(key in body)) {
          if (key === "deviation") {
            return refusal(
              "uncertainty_malformed",
              [...loc, key],
              `'${name}' is uncertain within a range, so it says how far: a deviation, as a fraction of each value (0.1 for ten per cent)`
            );
          }
          continue;
        }
        const value = body[key];
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
          return refusal("uncertainty_malformed", [...loc, key], `'${name}''s ${key} is a non-negative number`);
        }
      }
    }
    return null;
  }

  checkVariables(): IrRefusal | null {
    const variables = this.ir.variables;
    if (!isObject(variables)) {
      return refusal(
        "variables_not_object",
        ["variables"],
        "variables must be an object keyed by name"
      );
    }
    if (Object.keys(variables).length === 0) {
      return refusal(
        "variables_empty",
        ["variables"],
        "a model declares at least one variable; there is nothing here to decide"
      );
    }
    for (const [name, declaration] of Object.entries(variables)) {
      const at: IrLoc = ["variables", name];
      if (!isName(name)) {
        return refusal(
          "variable_not_a_name",
          at,
          `${show(name)} is not a variable name; names on this platform are ^[a-z][a-z0-9_]*$`
        );
      }
      if (!isObject(declaration)) {
        return refusal(
          "variable_not_object",
          at,
          `the declaration of '${name}' must be an object carrying its index and domain`
        );
      }
      const problem = unknownKey(declaration, VARIABLE_KEYS, at, "variable declaration");
      if (problem) return problem;
      const index = declaration.index;
      if (
        !Array.isArray(index) ||
        index.length > MAX_INDICES ||
        !index.every((s) => typeof s === "string")
      ) {
        return refusal(
          "variable_index_not_array",
          [...at, "index"],
          `'${name}' must declare index as an array of up to ${MAX_INDICES} set names; a ` +
            "scalar variable declares an empty one"
        );
      }
      for (let j = 0; j < index.length; j += 1) {
        if (!this.sets.has(index[j] as string)) {
          return refusal(
            "variable_index_not_declared",
            [...at, "index", j],
            `'${name}' is indexed by ${show(index[j])}, which this model does not declare in ` +
              "sets, so nothing would size it"
          );
        }
      }
      if (!("domain" in declaration)) {
        return refusal(
          "variable_domain_missing",
          [...at, "domain"],
          `'${name}' must declare a domain: it is what decides the model's class, so nothing ` +
            "defaults it"
        );
      }
      const domain = declaration.domain;
      if (!(VARIABLE_DOMAINS as readonly unknown[]).includes(domain)) {
        return refusal(
          "variable_domain_unsupported",
          [...at, "domain"],
          `${show(domain)} is not a variable domain version ${IR_VERSION} solves; it has ` +
            `${[...VARIABLE_DOMAINS].sort().join(", ")}`
        );
      }
      const intervalKeys = this.checkIntervalKeys(name, declaration, at);
      if (intervalKeys) return intervalKeys;
      const bounds = this.checkBounds(name, declaration, at);
      if (bounds) return bounds;
      const stage = this.checkStage(name, declaration, at);
      if (stage) return stage;
      this.variables.set(name, index as string[]);
    }
    for (const [name, declaration] of Object.entries(variables)) {
      if ((declaration as Json).domain === "interval") {
        const problem = this.checkIntervalParts(name, declaration as Json, ["variables", name]);
        if (problem) return problem;
      }
    }
    return null;
  }

  /** The same checks, in the same order, as `_check_interval_keys` in
   * `app/ir/validate.py`. */
  private checkIntervalKeys(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
    if (declaration.domain !== "interval") {
      const stray = INTERVAL_KEYS.filter((key) => key in declaration).sort();
      if (stray.length > 0) {
        return refusal(
          "interval_malformed",
          [...at, stray[0]],
          `'${name}' is ${String(declaration.domain)}, and only an interval names a ${stray[0]}`
        );
      }
      return null;
    }
    if (this.ir.version === 1) {
      return refusal(
        "interval_needs_version_2",
        [...at, "domain"],
        `'${name}' is an interval, which version 1 does not have; publish it as version 2`
      );
    }
    for (const key of ["start", "end", "size"]) {
      if (!(key in declaration)) {
        return refusal(
          "interval_malformed",
          [...at, key],
          `the interval '${name}' names no ${key}; an interval is a start, an end and the size between them`
        );
      }
    }
    for (const key of ["lower", "upper"]) {
      if (key in declaration) {
        return refusal(
          "interval_malformed",
          [...at, key],
          `the interval '${name}' carries a ${key} bound; its start and end variables carry the window it may be placed in`
        );
      }
    }
    return null;
  }

  /** `_check_interval_parts` in `app/ir/validate.py`. */
  private checkIntervalParts(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
    const index = this.variables.get(name) as string[];
    const declared = this.ir.variables as Record<string, Json>;
    const sameIndex = (other: string[] | undefined) =>
      other !== undefined && other.length === index.length && other.every((s, i) => s === index[i]);
    for (const [key, domain] of [
      ["start", "integer"],
      ["end", "integer"],
      ["presence", "binary"],
    ] as const) {
      if (!(key in declaration)) continue;
      const part = declaration[key];
      const spec = typeof part === "string" ? declared[part] : undefined;
      if (!isObject(spec) || spec.domain !== domain || !sameIndex(this.variables.get(part as string))) {
        return refusal(
          "interval_part_invalid",
          [...at, key],
          `the ${key} of the interval '${name}' must be ${domain === "integer" ? "an" : "a"} ${domain} ` +
            `variable declared over [${index.join(", ")}], as the interval is; ${show(part)} is not`
        );
      }
    }
    const size = declaration.size;
    if (typeof size === "string") {
      if (!sameIndex(this.parameters.get(size))) {
        return refusal(
          "interval_size_invalid",
          [...at, "size"],
          `the size of the interval '${name}' names ${show(size)}, which is not a parameter ` +
            `declared over [${index.join(", ")}], as the interval is`
        );
      }
    } else if (!isInt(size) || size < 0) {
      return refusal(
        "interval_size_invalid",
        [...at, "size"],
        `the size of the interval '${name}' is ${show(size)}; a size is a non-negative whole number, or a parameter`
      );
    }
    return null;
  }

  /** `_check_stage` in `app/ir/validate.py`, in the same order. */
  private checkStage(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
    if (!("stage" in declaration)) return null;
    const loc: IrLoc = [...at, "stage"];
    if (this.ir.version === 1) {
      return refusal(
        "stage_needs_version_2",
        loc,
        `'${name}' declares a stage, which version 1 does not have; publish it as version 2`
      );
    }
    const stage = declaration.stage;
    if (declaration.domain === "interval") {
      return refusal("stage_invalid", loc, `'${name}' is an interval; its start and end carry the stage`);
    }
    if (stage !== 1 && stage !== 2) {
      return refusal(
        "stage_invalid",
        loc,
        `'${name}''s stage is 1 (decided now) or 2 (decided once the uncertain data is known), not ${show(stage)}`
      );
    }
    return null;
  }

  private checkBounds(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
    if (declaration.domain === "interval") return null;
    for (const key of ["lower", "upper"] as const) {
      if (!(key in declaration)) continue;
      if (declaration.domain === "binary") {
        return refusal(
          "variable_bounds_invalid",
          [...at, key],
          `'${name}' is binary, so its bounds are 0 and 1 and it carries none`
        );
      }
      if (!isFiniteNumber(declaration[key])) {
        return refusal(
          "variable_bounds_invalid",
          [...at, key],
          `'${name}''s ${key} bound must be a number`
        );
      }
      if (declaration.domain === "integer" && !isInt(declaration[key])) {
        return refusal(
          "variable_bounds_invalid",
          [...at, key],
          `'${name}' is an integer variable, so its ${key} bound is a whole number; ` +
            `${show(declaration[key])} would be rounded by every solver that took it, and ` +
            "differently by some"
        );
      }
    }
    if ("lower" in declaration && "upper" in declaration) {
      if ((declaration.lower as number) > (declaration.upper as number)) {
        return refusal(
          "variable_bounds_invalid",
          [...at, "upper"],
          `'${name}' has lower ${declaration.lower} above upper ${declaration.upper}, so it ` +
            "has no admissible value"
        );
      }
    }
    return null;
  }

  checkConstraints(): IrRefusal | null {
    const constraints = this.ir.constraints;
    if (!Array.isArray(constraints)) {
      return refusal(
        "constraints_not_array",
        ["constraints"],
        "constraints must be an array; they are ordered and addressed by id"
      );
    }
    const seen = new Set<string>();
    for (let i = 0; i < constraints.length; i += 1) {
      const constraint = constraints[i];
      const at: IrLoc = ["constraints", i];
      if (!isObject(constraint)) {
        return refusal("constraint_not_object", at, "each constraint must be an object");
      }
      const unknown = unknownKey(constraint, CONSTRAINT_KEYS, at, "constraint");
      if (unknown) return unknown;
      const identifier = constraint.id;
      if (!isName(identifier)) {
        return refusal(
          "constraint_id_not_a_name",
          [...at, "id"],
          `${show(identifier)} is not a constraint id; ids travel into scenario.patch and ` +
            "constraint_result.constraint_id, and are ^[a-z][a-z0-9_]*$"
        );
      }
      if (seen.has(identifier)) {
        return refusal(
          "constraint_id_duplicated",
          [...at, "id"],
          `the constraint id '${identifier}' is used twice; constraint_result is keyed by it, ` +
            "so two constraints with one id could not both report"
        );
      }
      seen.add(identifier);

      let scope = new Map<string, string>();
      if ("forall" in constraint) {
        const bound = this.checkBindings(constraint.forall, [...at, "forall"], scope);
        if ("code" in bound) return bound as IrRefusal;
        scope = bound as Map<string, string>;
      }

      if ("chance" in constraint && ("connected" in constraint || "route" in constraint || "no_overlap" in constraint || "cumulative" in constraint)) {
        const problem = this.checkChance(constraint, at, identifier);
        if (problem) return problem;
      }
      if ("no_overlap" in constraint || "cumulative" in constraint) {
        const problem = this.checkScheduling(constraint, at, scope, identifier);
        if (problem) return problem;
        continue;
      }
      if ("connected" in constraint) {
        const problem = this.checkConnected(constraint, at, identifier);
        if (problem) return problem;
        continue;
      }
      if ("route" in constraint) {
        const problem = this.checkRoute(constraint, at, identifier);
        if (problem) return problem;
        continue;
      }

      for (const key of ["left", "relation", "right"] as const) {
        if (!(key in constraint)) {
          return refusal(
            "constraint_expression_missing",
            [...at, key],
            `the constraint '${identifier}' has no ${key}. A constraint that is named but not ` +
              "expressed cannot be solved, classified or diffed; if it is still being drafted, " +
              "leave it out of the version"
          );
        }
      }
      if (!(RELATIONS as readonly unknown[]).includes(constraint.relation)) {
        return refusal(
          "constraint_relation_unsupported",
          [...at, "relation"],
          `${show(constraint.relation)} is not a relation version ${IR_VERSION} expresses; it ` +
            `has ${[...RELATIONS].sort().join(", ")}`
        );
      }
      if (!(SEVERITIES as readonly unknown[]).includes(constraint.severity)) {
        return refusal(
          "constraint_severity_unsupported",
          [...at, "severity"],
          `${show(constraint.severity)} is not a severity; a constraint is ` +
            `${[...SEVERITIES].sort().join(" or ")}, and nothing defaults it`
        );
      }
      const weight = this.checkWeight(constraint, at, identifier);
      if (weight) return weight;

      for (const key of ["left", "right"] as const) {
        const problem = this.checkTerm(constraint[key], [...at, key], scope, 1);
        if (problem) return problem;
      }
      const when = this.checkWhen(constraint, at, scope, identifier);
      if (when) return when;
      const chance = this.checkChance(constraint, at, identifier);
      if (chance) return chance;
    }
    return null;
  }

  /** `_check_chance` in `app/ir/validate.py`, in the same order. */
  private checkChance(constraint: Json, at: IrLoc, identifier: string): IrRefusal | null {
    if (!("chance" in constraint)) return null;
    const loc: IrLoc = [...at, "chance"];
    if (this.ir.version === 1) {
      return refusal(
        "chance_needs_version_2",
        loc,
        `the constraint ${show(identifier)} carries a chance, which version 1 does not have; publish it as version 2`
      );
    }
    const chance = constraint.chance;
    const epsilon = chance && typeof chance === "object" && !Array.isArray(chance) ? (chance as Json).epsilon : undefined;
    if (
      !chance || typeof chance !== "object" || Array.isArray(chance) ||
      Object.keys(chance).length !== 1 || !isFiniteNumber(epsilon) || !(epsilon > 0 && epsilon < 1)
    ) {
      return refusal(
        "chance_malformed",
        loc,
        'a chance is the share of futures the rule may fail in, strictly between 0 and 1: {"epsilon": 0.1} holds it in 90% of them'
      );
    }
    if ("connected" in constraint || "route" in constraint || "no_overlap" in constraint || "cumulative" in constraint) {
      return refusal("chance_misplaced", loc, `the constraint ${show(identifier)} is a scheduling, connected or route rule; a chance is on an expression rule`);
    }
    if (constraint.severity === "soft") {
      return refusal("chance_misplaced", loc, `the constraint ${show(identifier)} is soft; a rule that may bend at a cost needs no chance -- make it hard`);
    }
    if ("when" in constraint) {
      return refusal("chance_misplaced", loc, `the constraint ${show(identifier)} already has a when; a chance switches the rule itself`);
    }
    if (degree(constraint.left) > 1 || degree(constraint.right) > 1) {
      return refusal("chance_misplaced", loc, `the constraint ${show(identifier)} multiplies decisions; a chance rule is linear`);
    }
    return null;
  }

  /** `connected` (version 2): the same checks, in the same order and with
   * the same locs, as `_check_connected` in `app/ir/validate.py`. */
  private checkConnected(constraint: Json, at: IrLoc, identifier: string): IrRefusal | null {
    if (this.ir.version === 1) {
      return refusal(
        "connected_needs_version_2",
        at,
        `the constraint '${identifier}' is a connected rule, which version 1 does not have; publish it as version 2`
      );
    }
    const body = constraint.connected;
    const loc: IrLoc = [...at, "connected"];
    const beside = ["left", "relation", "right", "forall", "no_overlap", "cumulative"].filter((key) => key in constraint);
    if (beside.length > 0) {
      return refusal(
        "connected_malformed",
        [...at, beside[0]],
        `the constraint '${identifier}' is a connected rule and also carries ${beside[0]}; a connected rule is ` +
          "not also an expression, and binds its own indices"
      );
    }
    if (!isObject(body)) {
      return refusal(
        "connected_malformed",
        loc,
        "a connected rule names assign, units, groups and via, and optionally empty"
      );
    }
    let odd: string | undefined =
      ["assign", "units", "groups", "via"].find((key) => !(key in body)) ??
      Object.keys(body).find((key) => !CONNECTED_KEYS.includes(key));
    if (odd === undefined && "empty" in body && body.empty !== "forbidden" && body.empty !== "allowed") odd = "empty";
    if (odd !== undefined) {
      const what = !(odd in body) ? "missing" : odd === "empty" ? "forbidden or allowed" : "not one of them";
      return refusal(
        "connected_malformed",
        [...loc, odd],
        `a connected rule names assign, units, groups and via, and optionally empty (forbidden or allowed); '${odd}' is ${what}`
      );
    }
    for (const key of ["severity", "weight", "when"]) {
      if (key in constraint && (key !== "severity" || constraint[key] !== "hard")) {
        return refusal(
          "connected_on_soft",
          [...at, key],
          `the connected rule '${identifier}' is hard and unconditional; a piece that is half connected has no price`
        );
      }
    }
    if (constraint.severity !== "hard") {
      return refusal(
        "constraint_severity_unsupported",
        [...at, "severity"],
        `${show(constraint.severity)} is not a severity; a connected rule is hard`
      );
    }
    let scope = new Map<string, string>();
    for (const part of ["units", "groups"] as const) {
      const inner = this.checkBindings([body[part]], [...loc, part], scope);
      if ("code" in inner) {
        // One binding, addressed as the body's own key, not as a list.
        const problem = inner as IrRefusal;
        return { ...problem, loc: [...loc, part, ...problem.loc.slice(loc.length + 2)] };
      }
      scope = inner as Map<string, string>;
    }
    const assign = body.assign;
    if (!isObject(assign) || Object.keys(assign).length !== 2 || !("var" in assign) || !("index" in assign)) {
      return refusal(
        "connected_malformed",
        [...loc, "assign"],
        'a connected rule names its variable as {"var": "assign", "index": [unit, group]}'
      );
    }
    const expected = [(body.units as Json).index, (body.groups as Json).index];
    const index = assign.index;
    if (!Array.isArray(index) || index.length !== 2 || index[0] !== expected[0] || index[1] !== expected[1]) {
      return refusal(
        "connected_index_mismatch",
        [...loc, "assign", "index"],
        `'${String(assign.var)}' is read as [${expected.join(", ")}]: the units' index, then the groups' index`
      );
    }
    const reference = this.reference(assign, [...loc, "assign"], scope, "var", this.variables);
    if (reference) return reference;
    const declared = (this.ir.variables as Record<string, Json>)[assign.var as string];
    if (declared.domain !== "binary") {
      return refusal(
        "connected_not_binary",
        [...loc, "assign", "var"],
        `'${String(assign.var)}' must be binary: a unit is in a group or it is not`
      );
    }
    if (typeof body.via !== "string" || !this.relationships.has(body.via)) {
      return refusal(
        "connected_via_invalid",
        [...loc, "via"],
        `${show(body.via)} is not a relationship this model declares in relationships, so no dataset would carry its edges`
      );
    }
    return null;
  }

  /** `route` (version 2, queue R15b): the same checks, in the same order and
   * with the same locs, as `_check_route` in `app/ir/validate.py`. */
  private checkRoute(constraint: Json, at: IrLoc, identifier: string): IrRefusal | null {
    if (this.ir.version === 1) {
      return refusal(
        "route_needs_version_2",
        at,
        `the constraint '${identifier}' is a route rule, which version 1 does not have; publish it as version 2`
      );
    }
    const body = constraint.route;
    const loc: IrLoc = [...at, "route"];
    const beside = ["left", "relation", "right", "forall", "connected", "no_overlap", "cumulative"].filter((key) => key in constraint);
    if (beside.length > 0) {
      return refusal(
        "route_malformed",
        [...at, beside[0]],
        `the constraint '${identifier}' is a route rule and also carries ${beside[0]}; a route rule is ` +
          "not also an expression, and binds its own indices"
      );
    }
    if (!isObject(body)) {
      return refusal(
        "route_malformed",
        loc,
        "a route rule names visit, vehicles, stops and depot, and optionally demand and capacity and time windows (travel, earliest, latest, service)"
      );
    }
    let odd: string | undefined;
    let what = "";
    odd = ["visit", "vehicles", "stops"].find((key) => !(key in body));
    if (odd !== undefined) what = "missing";
    // One depot for all, or each vehicle's own (`depot_of`; benchmark, October 2026), or the stop each
    // vehicle is linked to (`depot_by`; benchmark re-test, October 2026).
    const homes = ["depot", "depot_of", "depot_by"].filter((key) => key in body);
    if (odd === undefined && homes.length !== 1) {
      [odd, what] = homes.length === 0
        ? ["depot", "missing (or depot_of: the field of each vehicle naming its own depot; or depot_by: a relationship linking each vehicle to its own)"]
        : [homes[1], `given with ${homes[0]}: name one depot for all, or each vehicle's own, one way`];
    }
    if (odd === undefined) {
      odd = Object.keys(body).find((key) => !ROUTE_KEYS.includes(key));
      what = "not one of them";
    }
    if (odd === undefined) {
      odd = ["depot", "depot_of", "depot_by", "demand", "capacity", "travel", "earliest", "latest", "service"].find(
        (key) => key in body && !(typeof body[key] === "string" && body[key] !== "")
      );
      what = "not a name";
    }
    if (odd === undefined && ("demand" in body) !== ("capacity" in body)) {
      odd = "demand" in body ? "capacity" : "demand";
      what = "missing: demand and capacity come together";
    }
    if (odd === undefined && !("travel" in body)) {
      // Queue R15c: a window is kept in time, and time needs the travel between stops.
      odd = ["earliest", "latest", "service"].find((key) => key in body);
      what = "given without travel, the time from stop to stop";
    }
    if (odd !== undefined) {
      return refusal(
        "route_malformed",
        [...loc, odd],
        `a route rule names visit, vehicles, stops and depot, and optionally demand and capacity (both or neither); '${odd}' is ${what}`
      );
    }
    if ("depot_by" in body && !this.relationships.has(body.depot_by as string)) {
      return refusal(
        "route_malformed",
        [...loc, "depot_by"],
        `${show(body.depot_by)} is not a relationship this model declares in relationships, so no dataset would carry its links`
      );
    }
    for (const key of ["severity", "weight", "when"]) {
      if (key in constraint && (key !== "severity" || constraint[key] !== "hard")) {
        return refusal(
          "route_on_soft",
          [...at, key],
          `the route rule '${identifier}' is hard and unconditional; a stop half visited has no price`
        );
      }
    }
    if (constraint.severity !== "hard") {
      return refusal(
        "constraint_severity_unsupported",
        [...at, "severity"],
        `${show(constraint.severity)} is not a severity; a route rule is hard`
      );
    }
    let scope = new Map<string, string>();
    for (const part of ["vehicles", "stops"] as const) {
      const inner = this.checkBindings([body[part]], [...loc, part], scope);
      if ("code" in inner) {
        const problem = inner as IrRefusal;
        return { ...problem, loc: [...loc, part, ...problem.loc.slice(loc.length + 2)] };
      }
      scope = inner as Map<string, string>;
    }
    const visit = body.visit;
    if (!isObject(visit) || Object.keys(visit).length !== 2 || !("var" in visit) || !("index" in visit) || !Array.isArray(visit.index)) {
      return refusal(
        "route_malformed",
        [...loc, "visit"],
        'a route rule names its variable as {"var": "visit", "index": [vehicle, stop, next stop]}'
      );
    }
    const vehicle = (body.vehicles as Json).index as string;
    const stop = (body.stops as Json).index as string;
    const index = visit.index as unknown[];
    if (index.length !== 3 || index[0] !== vehicle || index[1] !== stop || typeof index[2] !== "string" || index[2] === vehicle || index[2] === stop) {
      return refusal(
        "route_index_mismatch",
        [...loc, "visit", "index"],
        `'${String(visit.var)}' is read as [${vehicle}, ${stop}, <next stop>]: the vehicles' index, the stops' index, then a third name for the stop it goes to`
      );
    }
    const withNext = new Map(scope);
    withNext.set(index[2] as string, (body.stops as Json).set as string);
    const reference = this.reference(visit, [...loc, "visit"], withNext, "var", this.variables);
    if (reference) return reference;
    const declared = (this.ir.variables as Record<string, Json>)[visit.var as string];
    if (declared.domain !== "binary") {
      return refusal(
        "route_not_binary",
        [...loc, "visit", "var"],
        `'${String(visit.var)}' must be binary: a vehicle goes from one stop to the next or it does not`
      );
    }
    if ("travel" in body) {
      const stops = (body.stops as Json).set as string;
      const index = this.parameters.get(body.travel as string);
      if (!index || index.length !== 2 || index[0] !== stops || index[1] !== stops || this.entityParameters.has(body.travel as string)) {
        return refusal(
          "route_travel_invalid",
          [...loc, "travel"],
          `${show(body.travel)} must be a parameter this model declares over [${stops}, ${stops}]: the time from each stop to the next`
        );
      }
    }
    return null;
  }

  /** `no_overlap` / `cumulative` (version 2): the same checks, in the same
   * order, as `_check_scheduling` in `app/ir/validate.py`. */
  private checkScheduling(
    constraint: Json,
    at: IrLoc,
    scope: Map<string, string>,
    identifier: string
  ): IrRefusal | null {
    const kinds = (["no_overlap", "cumulative"] as const).filter((kind) => kind in constraint);
    const kind = kinds[0];
    if (this.ir.version === 1) {
      return refusal(
        "scheduling_needs_version_2",
        at,
        `the constraint '${identifier}' is a ${kind} rule, which version 1 does not have; publish it as version 2`
      );
    }
    const extra = [...kinds.slice(1), ...["left", "relation", "right"].filter((key) => key in constraint)];
    if (extra.length > 0) {
      return refusal(
        "scheduling_rule_malformed",
        [...at, extra[0]],
        `the constraint '${identifier}' is a ${kind} rule and also carries ${extra[0]}; a constraint is ` +
          "one expression or one scheduling rule"
      );
    }
    const body = constraint[kind];
    const loc: IrLoc = [...at, kind];
    const expected = SCHEDULING_KEYS[kind];
    if (
      !isObject(body) ||
      Object.keys(body).length !== expected.length ||
      !expected.every((key) => key in body)
    ) {
      return refusal(
        "scheduling_rule_malformed",
        loc,
        `a ${kind} carries exactly ${[...expected].sort().join(", ")}`
      );
    }
    if (!(SEVERITIES as readonly unknown[]).includes(constraint.severity)) {
      return refusal(
        "constraint_severity_unsupported",
        [...at, "severity"],
        `${show(constraint.severity)} is not a severity; a constraint is ` +
          `${[...SEVERITIES].sort().join(" or ")}, and nothing defaults it`
      );
    }
    for (const key of ["severity", "weight", "when"]) {
      if (key in constraint && (key !== "severity" || constraint[key] !== "hard")) {
        return refusal(
          "scheduling_rule_hard",
          [...at, key],
          `the ${kind} rule '${identifier}' is hard and unconditional; a scheduling rule has no ` +
            "price for being broken and no switch"
        );
      }
    }
    const inner = this.checkBindings(body.over, [...loc, "over"], scope);
    if ("code" in inner) return inner as IrRefusal;
    const innerScope = inner as Map<string, string>;
    const interval = body.interval;
    if (
      !isObject(interval) ||
      Object.keys(interval).length !== 2 ||
      !("var" in interval) ||
      !("index" in interval)
    ) {
      return refusal(
        "scheduling_rule_malformed",
        [...loc, "interval"],
        'a scheduling rule names its intervals as {"var": "task", "index": [...]}'
      );
    }
    const reference = this.reference(interval, [...loc, "interval"], innerScope, "var", this.variables);
    if (reference) return reference;
    const declared = (this.ir.variables as Record<string, Json>)[interval.var as string];
    if (declared.domain !== "interval") {
      return refusal(
        "scheduling_not_interval",
        [...loc, "interval", "var"],
        `'${String(interval.var)}' is ${String(declared.domain)}; a ${kind} rule is over interval variables`
      );
    }
    if (kind === "cumulative") {
      for (const [key, where] of [
        ["demand", innerScope],
        ["capacity", scope],
      ] as const) {
        const problem = this.checkTerm(body[key], [...loc, key], where, 1);
        if (problem) return problem;
        if (degree(body[key]) > 0) {
          return refusal(
            "scheduling_amount_not_constant",
            [...loc, key],
            `the ${key} of '${identifier}' reads a decision; it is a number the data gives`
          );
        }
      }
    }
    return null;
  }

  /** `when`: the rule holds only while a binary variable is `is` (1 by
   * default). The same checks, in the same order, as `_check_when` in
   * `app/ir/validate.py`. */
  private checkWhen(
    constraint: Json,
    at: IrLoc,
    scope: Map<string, string>,
    identifier: string
  ): IrRefusal | null {
    if (!("when" in constraint)) return null;
    const when = constraint.when;
    const loc: IrLoc = [...at, "when"];
    if (this.ir.version === 1) {
      return refusal(
        "when_needs_version_2",
        loc,
        `the constraint ${show(identifier)} carries a when, which version 1 does not have; ` +
          "publish it as version 2"
      );
    }
    if (
      !isObject(when) ||
      Object.keys(when).some((key) => !["var", "index", "is"].includes(key)) ||
      !("var" in when) ||
      !("index" in when) ||
      ("is" in when && when.is !== 0 && when.is !== 1)
    ) {
      return refusal(
        "when_malformed",
        loc,
        "a when names a binary variable and its index, and optionally the value it must have " +
          'for the rule to hold: {"var": "open", "index": ["f"], "is": 1}'
      );
    }
    const problem = this.checkTerm({ var: when.var, index: when.index }, loc, scope, 1);
    if (problem) return problem;
    const variables = isObject(this.ir.variables) ? this.ir.variables : {};
    const declared = isObject(variables[when.var as string]) ? (variables[when.var as string] as Json) : {};
    if (declared.domain !== "binary") {
      return refusal(
        "when_not_binary",
        [...loc, "var"],
        `${show(when.var)} is ${show(declared.domain)}; a when switches a rule on and off, ` +
          "so it names a yes-or-no decision"
      );
    }
    if (constraint.severity === "soft") {
      return refusal(
        "when_on_soft",
        loc,
        `the constraint ${show(identifier)} is soft and conditional; a rule that may be broken ` +
          "at a cost needs no switch -- make it hard, or drop the when"
      );
    }
    if (degree(constraint.left) > 1 || degree(constraint.right) > 1) {
      return refusal(
        "when_on_product",
        loc,
        `the constraint ${show(identifier)} multiplies decisions and carries a when; a ` +
          "conditional rule is linear"
      );
    }
    return null;
  }

  private checkWeight(constraint: Json, at: IrLoc, identifier: string): IrRefusal | null {
    const weight = constraint.weight;
    if (constraint.severity === "soft") {
      if (!isInt(weight) || weight < 1) {
        return refusal(
          "constraint_weight_invalid",
          [...at, "weight"],
          `the soft constraint '${identifier}' must carry a positive integer weight; a soft ` +
            "constraint with no penalty is one the solver may ignore for free"
        );
      }
    } else if ("weight" in constraint) {
      return refusal(
        "constraint_weight_invalid",
        [...at, "weight"],
        `the hard constraint '${identifier}' carries a weight; a hard constraint has no ` +
          "penalty, so soften it in a scenario instead"
      );
    }
    return null;
  }

  checkBindings(
    bindings: unknown,
    loc: IrLoc,
    outer: Map<string, string>
  ): Map<string, string> | IrRefusal {
    if (!Array.isArray(bindings) || bindings.length < 1 || bindings.length > MAX_INDICES) {
      return refusal(
        "bindings_invalid",
        loc,
        `this must be an array binding between 1 and ${MAX_INDICES} indices; omit the key ` +
          "entirely when there is nothing to range over"
      );
    }
    const scope = new Map(outer);
    for (let j = 0; j < bindings.length; j += 1) {
      const binding = bindings[j];
      const at: IrLoc = [...loc, j];
      if (!isObject(binding)) {
        return refusal(
          "binding_not_object",
          at,
          "a binding names an index and the set it ranges over"
        );
      }
      const unknown = unknownKey(binding, BINDING_KEYS, at, "binding");
      if (unknown) return unknown;
      const index = binding.index;
      if (!isName(index)) {
        return refusal(
          "binding_index_not_a_name",
          [...at, "index"],
          `${show(index)} is not an index name; names on this platform are ^[a-z][a-z0-9_]*$`
        );
      }
      if (scope.has(index)) {
        return refusal(
          "binding_index_duplicated",
          [...at, "index"],
          `the index '${index}' is already bound here; shadowing would leave which one a term ` +
            "meant to the reader"
        );
      }
      const setName = binding.set;
      if (typeof setName !== "string" || !this.sets.has(setName)) {
        return refusal(
          "binding_set_not_declared",
          [...at, "set"],
          `${show(setName)} is not a set this model declares, so no dataset would carry it`
        );
      }
      // Order matters here and is the whole reason `via` is a binding rather
      // than a term: the anchor must already be bound when the traversal
      // starts, so it is checked against `scope` BEFORE this binding's own
      // index joins it. Checking afterwards would let a binding walk from
      // itself.
      const via = this.checkVia(binding, at, scope);
      if (via) return via;
      scope.set(index, setName);
      const edge = this.checkEdge(binding, at, scope);
      if (edge) return edge;
      const where = this.checkWhere(binding, at, new Map([...scope].filter(([k]) => k !== index)));
      if (where) return where;
    }
    return scope;
  }

  /** A `via` may name the edge it walks (queue R19), so a term can read the
   * edge's own attributes. The name joins the scope after the binding's
   * index, marked as an edge. */
  private checkEdge(binding: Json, at: IrLoc, scope: Map<string, string>): IrRefusal | null {
    const via = binding.via;
    if (!isObject(via) || !("as" in via)) return null;
    const here: IrLoc = [...at, "via", "as"];
    if (this.ir.version === 1) {
      return refusal(
        "edge_needs_version_2",
        here,
        "reading an edge's attributes is version 2; write version 2 to name the edge"
      );
    }
    const name = via.as;
    if (!isName(name) || scope.has(name as string)) {
      return refusal(
        "binding_via_as_invalid",
        here,
        `${show(name)} cannot name this edge: it is ` +
          (isName(name) ? "already bound here" : "not a name (^[a-z][a-z0-9_]*$)")
      );
    }
    scope.set(name as string, `${EDGE_MARK}${String(via.rel)}/${singleStep(via) ? "one" : "path"}`);
    return null;
  }

  private checkVia(binding: Json, at: IrLoc, scope: Map<string, string>): IrRefusal | null {
    if (!("via" in binding)) return null;
    const via = binding.via;
    const here: IrLoc = [...at, "via"];
    if (!isObject(via)) {
      return refusal(
        "binding_via_not_object",
        here,
        "a via names the relationship to walk and which end this binding starts from"
      );
    }
    const unknown = unknownKey(via, VIA_KEYS, here, "via");
    if (unknown) return unknown;

    const rel = via.rel;
    if (typeof rel !== "string" || !this.relationships.has(rel)) {
      return refusal(
        "binding_via_rel_not_declared",
        [...here, "rel"],
        `${show(rel)} is not a relationship this model declares in relationships, so no ` +
          "dataset would carry its edges"
      );
    }

    const ends = VIA_ENDS.filter((end) => end in via);
    if (ends.length !== 1 || !isName(via[ends[0]])) {
      return refusal(
        "binding_via_anchor_invalid",
        here,
        "a via names exactly one of from, to or both, and it is the index the walk starts at; " +
          "the end named is where that index sits, so this binding takes the other (both: " +
          "either end, the links walked either way)"
      );
    }
    const anchor = via[ends[0]] as string;
    if (isEdge(scope.get(anchor))) {
      return refusal(
        "edge_not_an_index",
        [...here, ends[0]],
        `'${anchor}' is an edge a via names with as; a walk starts at an entity index`
      );
    }
    if (!scope.has(anchor)) {
      return refusal(
        "binding_via_anchor_not_bound",
        [...here, ends[0]],
        `the index '${anchor}' is not bound where this traversal starts; bind it in an ` +
          "enclosing forall, or earlier in this same list"
      );
    }
    if ("depth" in via && !(TRAVERSAL_DEPTHS as readonly string[]).includes(via.depth as string)) {
      return refusal(
        "binding_via_depth_unsupported",
        [...here, "depth"],
        `${show(via.depth)} is not a depth version ${IR_VERSION} walks; it has ` +
          `${[...TRAVERSAL_DEPTHS].sort().join(", ")}`
      );
    }
    if ("steps" in via) {
      const steps = via.steps;
      const low = isObject(steps) ? steps.min : undefined;
      const high = isObject(steps) ? steps.max : undefined;
      if (
        "depth" in via ||
        !isObject(steps) ||
        Object.keys(steps).some((key) => !STEPS_KEYS.has(key)) ||
        !isInt(low) ||
        low < 0 ||
        ("max" in steps && (!isInt(high) || high < Math.max(low, 1)))
      ) {
        return refusal(
          "binding_via_steps_invalid",
          [...here, "steps"],
          'steps is {"min": m, "max": n}: whole numbers with 0 <= m <= n and n at least 1, or no ' +
            "max for no limit; it says how far a walk goes, so it is never beside depth"
        );
      }
    }
    if ("on" in via && !isDate(via.on)) {
      return refusal(
        "binding_via_on_invalid",
        [...here, "on"],
        `${show(via.on)} is not a date; on is YYYY-MM-DD, and only the links valid that day are walked`
      );
    }
    if ("where" in via) {
      // Conditions on the links themselves: a walk follows only the links that pass.
      const problem = this.checkFilters(via.where, [...here, "where"], undefined, new Map());
      if (problem) return problem;
    }
    return null;
  }

  private checkWhere(binding: Json, at: IrLoc, scope: Map<string, string> = new Map()): IrRefusal | null {
    if (!("where" in binding)) return null;
    return this.checkFilters(binding.where, [...at, "where"], binding.set as string | undefined, scope);
  }

  /** A `where` list -- a binding's own, or a walk's conditions on its links (`set` undefined).
   * Each entry is a filter, or a group {"any": [...]} that holds when one of its filters does. */
  private checkFilters(filters: unknown, at: IrLoc, set: string | undefined, scope: Map<string, string>): IrRefusal | null {
    if (!Array.isArray(filters)) {
      return refusal(
        "where_not_array",
        at,
        'where is an array of filters, combined with and; a group {"any": [...]} among them holds ' +
          "when any of its filters does"
      );
    }
    for (let k = 0; k < filters.length; k += 1) {
      const entry = filters[k];
      const here: IrLoc = [...at, k];
      if (isObject(entry) && "any" in entry) {
        const group = entry.any;
        if (
          Object.keys(entry).length !== 1 ||
          !Array.isArray(group) ||
          group.length < 2 ||
          !group.every((g) => isObject(g) && !("any" in g) && !("index" in g) && !isObject(g.value))
        ) {
          return refusal(
            "where_group_malformed",
            here,
            'a group is {"any": [two or more filters]}, one level deep, each comparing with a ' +
              "value; it holds when any of its filters does"
          );
        }
        for (let g = 0; g < group.length; g += 1) {
          const problem = this.checkFilter(group[g], [...here, "any", g], set, scope);
          if (problem) return problem;
        }
        continue;
      }
      const problem = this.checkFilter(entry, here, set, scope);
      if (problem) return problem;
    }
    return null;
  }

  private checkFilter(entry: unknown, here: IrLoc, set: string | undefined, scope: Map<string, string>): IrRefusal | null {
    if (!isObject(entry)) {
      return refusal("where_filter_malformed", here, "each filter must be an object");
    }
    if ("index" in entry) {
      // "a != b": this item against one bound earlier, of the same set (benchmark, October 2026).
      const other = entry.index;
      const keys = Object.keys(entry);
      if (
        keys.length !== 2 || !keys.includes("op") ||
        !INDEX_OPERATORS.includes(entry.op as string) ||
        set === undefined || typeof other !== "string" || scope.get(other) !== set
      ) {
        return refusal(
          "where_index_invalid",
          here,
          `a filter compares this item with another as {"index": name, "op": one of ${INDEX_OPERATORS.join(", ")}}, ` +
            `the other bound earlier over the same set ('${set}')`
        );
      }
      return null;
    }
    const unknown = unknownKey(entry, FILTER_KEYS, here, "filter");
    if (unknown) return unknown;
    if (!isName(entry.attr)) {
      return refusal(
        "where_filter_malformed",
        [...here, "attr"],
        "a filter names an attribute of the set its binding ranges over"
      );
    }
    const operator = entry.op;
    if (typeof operator !== "string") {
      return refusal(
        "where_filter_malformed",
        [...here, "op"],
        `a filter names a comparison; version ${IR_VERSION} has no unary filters, so op is ` +
          "never absent"
      );
    }
    if (!(FILTER_OPERATORS as readonly string[]).includes(operator)) {
      return refusal(
        "where_operator_unknown",
        [...here, "op"],
        `${show(operator)} is not a filter comparison; the vocabulary is the expression ` +
          `catalogue's, narrowed to ${[...FILTER_OPERATORS].sort().join(", ")}`
      );
    }
    if (!("value" in entry)) {
      return refusal("where_filter_malformed", [...here, "value"], "a filter carries a value");
    }
    const value = entry.value;
    if (isObject(value)) {
      // Queue R20b: `id = preferred_shift[e, d]`, the row being the entity that cell holds.
      const fits =
        entry.attr === "id" &&
        (operator === "=" || operator === "!=") &&
        Object.keys(value).length === 2 &&
        "par" in value &&
        "index" in value &&
        set !== undefined &&
        this.entityParameters.get(value.par as string) === set;
      if (!fits) {
        return refusal(
          "where_parameter_invalid",
          [...here, "value"],
          "a filter compares with a parameter only as id = or != a parameter whose values are entities of " +
            `'${String(set)}'`
        );
      }
      return this.reference(value, [...here, "value"], scope, "par", this.parameters);
    }
    const ok = LIST_OPERATORS.has(operator)
      ? Array.isArray(value) && value.length > 0 && value.every(isScalar)
      : isScalar(value);
    if (!ok) {
      return refusal(
        "where_filter_malformed",
        [...here, "value"],
        `${show(operator)} takes ` +
          (LIST_OPERATORS.has(operator) ? "a non-empty array of values" : "a single value")
      );
    }
    return null;
  }

  checkTerm(
    term: unknown,
    loc: IrLoc,
    scope: Map<string, string>,
    depth: number
  ): IrRefusal | null {
    if (depth > MAX_DEPTH) {
      return refusal(
        "depth_exceeded",
        loc,
        `this term nests deeper than ${MAX_DEPTH}, which is past what a builder can render and ` +
          "a reader can check"
      );
    }
    this.terms += 1;
    if (this.terms > MAX_TERMS) {
      return refusal(
        "terms_exceeded",
        loc,
        `this model holds more than ${MAX_TERMS} terms; this one took it past the limit`
      );
    }
    if (!isObject(term)) {
      return refusal(
        "term_not_object",
        loc,
        "every term is an object naming its kind, so nothing has to be inferred"
      );
    }
    const kinds = TERM_KINDS.filter((kind) => kind in term);
    if (kinds.length === 0) {
      return refusal(
        "term_kind_unknown",
        loc,
        `a term names one of ${[...TERM_KINDS].sort().join(", ")}; this names none of them`
      );
    }
    if (kinds.length > 1) {
      return refusal(
        "term_kind_ambiguous",
        loc,
        `this term names ${[...kinds].sort().join(" and ")}; which one wins would be left to ` +
          "key order"
      );
    }
    const kind = kinds[0];
    const unknown = unknownKey(
      term,
      new Set([kind, ...TERM_KEYS[kind]]),
      loc,
      `${kind} term`
    );
    if (unknown) return unknown;
    switch (kind) {
      case "const":
        return this.termConst(term, loc);
      case "par":
        if (this.entityParameters.has(term.par as string)) {
          return refusal(
            "entity_parameter_read_as_number",
            [...loc, "par"],
            `'${String(term.par)}''s values are entities of ${this.entityParameters.get(term.par as string)}, not ` +
              "numbers; use it as an index, or in a filter (id = ...)"
          );
        }
        return this.reference(term, loc, scope, "par", this.parameters);
      case "var": {
        const problem = this.reference(term, loc, scope, "var", this.variables);
        if (problem) return problem;
        const declared = (this.ir.variables as Record<string, Json>)[term.var as string];
        if (declared.domain === "interval") {
          return refusal(
            "interval_read_as_number",
            [...loc, "var"],
            `'${String(term.var)}' is an interval, which is not a number; read its start or end variable instead`
          );
        }
        return null;
      }
      case "attr":
        return this.termAttr(term, loc, scope);
      case "sum":
        return this.termSum(term, loc, scope, depth);
      case "add":
        return this.termAdd(term, loc, scope, depth);
      case "pwl":
        return this.termPwl(term, loc, scope, depth);
      case "fn":
        return this.termFn(term, loc, scope, depth);
      case "predict":
        return this.termPredict(term, loc, scope, depth);
      default:
        return this.termMul(term, loc, scope, depth);
    }
  }

  private termConst(term: Json, loc: IrLoc): IrRefusal | null {
    if (!isFiniteNumber(term.const)) {
      return refusal("const_not_a_number", [...loc, "const"], `${show(term.const)} is not a number`);
    }
    return null;
  }

  /** `{par, index}` standing for an entity: an entity-valued parameter, of the set wanted, read here. */
  private entityIndex(ref: Json, loc: IrLoc, scope: Map<string, string>, wanted: string | undefined): IrRefusal | null {
    const keys = Object.keys(ref);
    if (keys.length !== 2 || !("par" in ref) || !("index" in ref) || !this.entityParameters.has(ref.par as string)) {
      // In words (benchmark round 4: `amount[of_parcel[h], of_crop[h]]` was answered with raw JSON).
      const attr = ref && typeof ref === "object" ? (ref as { attr?: { name?: unknown } }).attr : undefined;
      const field = attr && typeof attr === "object" && typeof attr.name === "string" ? attr.name : null;
      return refusal(
        "index_entry_invalid",
        loc,
        'each position in [...] takes an index (like p, bound by "for each" or a sum) or a data value whose ' +
          "values are records" +
          (field
            ? `; a record's own field (${field}) cannot choose the position -- sum over the records instead ` +
              `and keep the ones whose ${field} matches, or make a data value from it`
            : "")
      );
    }
    const of = this.entityParameters.get(ref.par as string);
    if (wanted !== undefined && of !== wanted) {
      return refusal(
        "index_entry_invalid",
        [...loc, "par"],
        `'${String(ref.par)}' gives an entity of ${of}, but this position takes one of ${wanted}`
      );
    }
    return this.reference(ref, loc, scope, "par", this.parameters);
  }

  private reference(
    term: Json,
    loc: IrLoc,
    scope: Map<string, string>,
    kind: "par" | "var",
    declared: Map<string, string[]>
  ): IrRefusal | null {
    const name = term[kind];
    const what = kind === "par" ? "parameter" : "variable";
    if (typeof name !== "string" || !declared.has(name)) {
      return refusal(
        "reference_undeclared",
        [...loc, kind],
        `${show(name)} is not a ${what} this model declares`
      );
    }
    const indexTypes = declared.get(name) as string[];
    const subscript = term.index;
    if (!Array.isArray(subscript) || subscript.length !== indexTypes.length) {
      return refusal(
        "reference_index_arity",
        [...loc, "index"],
        `'${name}' is declared over ${indexTypes.length} ` +
          `${indexTypes.length === 1 ? "set" : "sets"} (${indexTypes.join(", ") || "none"}), so ` +
          "it is subscripted with that many indices"
      );
    }
    for (let j = 0; j < subscript.length; j += 1) {
      const index = subscript[j];
      if (isObject(index)) {
        // Queue R20b: `preferred_shift[e, d]` in a position -- the entity that cell holds.
        const problem = this.entityIndex(index, [...loc, "index", j], scope, indexTypes[j]);
        if (problem) return problem;
        continue;
      }
      if (typeof index === "string" && isEdge(scope.get(index))) {
        return refusal(
          "edge_not_an_index",
          [...loc, "index", j],
          `'${index}' is an edge a via names with as; read its attributes with attr, and ` +
            "subscript with the entity index the walk lands on"
        );
      }
      if (typeof index !== "string" || !scope.has(index)) {
        return refusal(
          "index_not_bound",
          [...loc, "index", j],
          `${show(index)} is not bound by any enclosing forall or over, so it has no range`
        );
      }
      if (scope.get(index) !== indexTypes[j]) {
        return refusal(
          "index_set_mismatch",
          [...loc, "index", j],
          `'${name}' is indexed by '${indexTypes[j]}' in position ${j}, but '${index}' ranges ` +
            `over '${scope.get(index)}'`
        );
      }
    }
    return null;
  }

  private termAttr(term: Json, loc: IrLoc, scope: Map<string, string>): IrRefusal | null {
    const reference = term.attr;
    if (
      !isObject(reference) ||
      !("of" in reference) ||
      !("name" in reference) ||
      Object.keys(reference).some((key) => !["of", "name", "along"].includes(key))
    ) {
      return refusal(
        "term_not_object",
        [...loc, "attr"],
        'an attr term is {"of": <index>, "name": <attribute>}, and an edge\'s read along a ' +
          'path adds "along"'
      );
    }
    if (typeof reference.of !== "string" || !scope.has(reference.of)) {
      return refusal(
        "index_not_bound",
        [...loc, "attr", "of"],
        `${show(reference.of)} is not bound by any enclosing forall or over`
      );
    }
    if (!isName(reference.name)) {
      return refusal(
        "term_not_object",
        [...loc, "attr", "name"],
        `${show(reference.name)} is not an attribute name; attribute_def.name is ` +
          "^[a-z][a-z0-9_]*$"
      );
    }
    const bound = scope.get(reference.of);
    const path = isEdge(bound) && !(bound as string).endsWith("/one");
    const along = reference.along;
    if (path && !(PATH_COMBINATIONS as readonly unknown[]).includes(along)) {
      return refusal(
        "attr_along_invalid",
        [...loc, "attr", "along" in reference ? "along" : "name"],
        `'${reference.of}' is the path of a walk that repeats, so its '${String(reference.name)}' ` +
          `is one value per edge; say how they combine: along ${[...PATH_COMBINATIONS].join(", ")}`
      );
    }
    if (!path && "along" in reference) {
      return refusal(
        "attr_along_invalid",
        [...loc, "attr", "along"],
        `'${reference.of}' is ${isEdge(bound) ? "one edge" : "an entity"}, so its attribute has ` +
          "one value and nothing to combine"
      );
    }
    return null;
  }

  private termSum(
    term: Json,
    loc: IrLoc,
    scope: Map<string, string>,
    depth: number
  ): IrRefusal | null {
    if (!("over" in term)) {
      return refusal(
        "sum_malformed",
        [...loc, "over"],
        "a sum ranges over something; without an over it is its own body under a misleading name"
      );
    }
    const bound = this.checkBindings(term.over, [...loc, "over"], scope);
    if ("code" in bound) return bound as IrRefusal;
    return this.checkTerm(term.sum, [...loc, "sum"], bound as Map<string, string>, depth + 1);
  }

  private termAdd(
    term: Json,
    loc: IrLoc,
    scope: Map<string, string>,
    depth: number
  ): IrRefusal | null {
    const summands = term.add;
    if (!Array.isArray(summands) || summands.length === 0) {
      return refusal(
        "add_empty",
        [...loc, "add"],
        'add carries at least one summand; zero is written {"const": 0}'
      );
    }
    for (let i = 0; i < summands.length; i += 1) {
      const problem = this.checkTerm(summands[i], [...loc, "add", i], scope, depth + 1);
      if (problem) return problem;
    }
    return null;
  }

  /** The same checks, in the same order, as `_term_pwl` in `app/ir/validate.py`. */
  private termPwl(
    term: Json,
    loc: IrLoc,
    scope: Map<string, string>,
    depth: number
  ): IrRefusal | null {
    if (this.ir.version === 1) {
      return refusal(
        "pwl_needs_version_2",
        [...loc, "pwl"],
        "a piecewise-linear term is version 2; publish the model as version 2"
      );
    }
    const argument = term.pwl;
    if (
      !isObject(argument) ||
      Object.keys(argument).length !== 2 ||
      !("var" in argument) ||
      !("index" in argument)
    ) {
      return refusal("pwl_malformed", [...loc, "pwl"], 'a pwl is a curve of one variable: {"var": "x", "index": [...]}');
    }
    const problem = this.checkTerm(argument, [...loc, "pwl"], scope, depth + 1);
    if (problem) return problem;
    const points = term.points;
    const isNumber = (n: unknown) => typeof n === "number" && Number.isFinite(n);
    if (
      !Array.isArray(points) ||
      points.length < 2 ||
      !points.every((p) => Array.isArray(p) && p.length === 2 && p.every(isNumber))
    ) {
      return refusal("pwl_malformed", [...loc, "points"], "a pwl's points are at least two [x, y] pairs of numbers");
    }
    const xs = (points as number[][]).map((p) => p[0]);
    if (xs.some((x, i) => i > 0 && x <= xs[i - 1])) {
      return refusal(
        "pwl_breakpoints_not_increasing",
        [...loc, "points"],
        "a pwl's points are in strictly increasing x, so each x has one value"
      );
    }
    return null;
  }

  /** The same checks, in the same order, as `check_predictors` in `app/ir/validate.py`. */
  checkPredictors(): IrRefusal | null {
    const predictors = this.ir.predictors;
    if (predictors === undefined || predictors === null) return null;
    if (this.ir.version === 1) {
      return refusal(
        "predict_needs_version_2",
        ["predictors"],
        "predictors are a version 2 construct; publish the model as version 2"
      );
    }
    if (!isObject(predictors)) {
      return refusal(
        "predictors_malformed",
        ["predictors"],
        'predictors is an object keyed by predictor name: {"demand_model": {"inputs": 2}}'
      );
    }
    for (const [name, declaration] of Object.entries(predictors)) {
      const at: IrLoc = ["predictors", name];
      if (!isName(name)) {
        return refusal(
          "predictors_malformed",
          at,
          `${show(name)} is not a predictor name; predictor.name is ^[a-z][a-z0-9_]*$`
        );
      }
      if (
        !isObject(declaration) ||
        Object.keys(declaration).length !== 1 ||
        !("inputs" in declaration) ||
        !isInt(declaration.inputs) ||
        declaration.inputs < 1 ||
        declaration.inputs > MAX_PREDICTOR_INPUTS
      ) {
        return refusal(
          "predictors_malformed",
          at,
          `'${name}' is declared as {"inputs": n}, n the number of inputs the model takes, 1 to ${MAX_PREDICTOR_INPUTS}`
        );
      }
      this.predictors.set(name, declaration.inputs as number);
    }
    return null;
  }

  /** The same checks, in the same order, as `_term_predict` in `app/ir/validate.py`. */
  private termPredict(term: Json, loc: IrLoc, scope: Map<string, string>, depth: number): IrRefusal | null {
    if (this.ir.version === 1) {
      return refusal("predict_needs_version_2", [...loc, "predict"], "a predict term is version 2; publish the model as version 2");
    }
    const name = term.predict;
    if (typeof name !== "string" || !this.predictors.has(name)) {
      const declared = [...this.predictors.keys()].sort().join(", ") || "none";
      return refusal(
        "predict_unknown",
        [...loc, "predict"],
        `${show(name)} is not a predictor this model declares in predictors (it declares ${declared})`
      );
    }
    const inputs = term.of;
    if (!Array.isArray(inputs) || inputs.length === 0) {
      return refusal(
        "predict_malformed",
        [...loc, "of"],
        `a prediction is made from its inputs: ${name} needs them as an array in \`of\``
      );
    }
    const wanted = this.predictors.get(name) as number;
    if (inputs.length !== wanted) {
      return refusal("predict_arity", [...loc, "of"], `${name} takes ${wanted} inputs and is given ${inputs.length}`);
    }
    for (let i = 0; i < inputs.length; i += 1) {
      const problem = this.checkTerm(inputs[i], [...loc, "of", i], scope, depth + 1);
      if (problem) return problem;
      if (degree(inputs[i]) > 1) {
        return refusal(
          "predict_argument_nonlinear",
          [...loc, "of", i],
          `input ${i} of ${name} multiplies decisions together; a predictor's inputs are linear`
        );
      }
    }
    return null;
  }

  /** The same checks, in the same order, as `_term_fn` in `app/ir/validate.py`. */
  private termFn(term: Json, loc: IrLoc, scope: Map<string, string>, depth: number): IrRefusal | null {
    if (this.ir.version === 1) {
      return refusal("fn_needs_version_2", [...loc, "fn"], "a function term is version 2; publish the model as version 2");
    }
    const name = term.fn;
    if (typeof name !== "string" || !Object.prototype.hasOwnProperty.call(FUNCTIONS, name)) {
      return refusal(
        "fn_unknown",
        [...loc, "fn"],
        `${show(name)} is not a function this platform knows; it knows ${Object.keys(FUNCTIONS).sort().join(", ")}`
      );
    }
    if (!("of" in term)) {
      return refusal("fn_malformed", [...loc, "of"], `a function is applied to something: ${name} needs its argument in \`of\``);
    }
    const problem = this.checkTerm(term.of, [...loc, "of"], scope, depth + 1);
    if (problem) return problem;
    if (degree(term.of) > 1) {
      return refusal(
        "fn_argument_nonlinear",
        [...loc, "of"],
        `the argument of ${name} multiplies decisions together; a function is applied to a linear argument`
      );
    }
    return null;
  }

  private termMul(
    term: Json,
    loc: IrLoc,
    scope: Map<string, string>,
    depth: number
  ): IrRefusal | null {
    const factors = term.mul;
    if (!Array.isArray(factors) || factors.length !== 2) {
      return refusal(
        "mul_arity",
        [...loc, "mul"],
        "mul has exactly two factors, so linearity is a check on a pair"
      );
    }
    for (let i = 0; i < factors.length; i += 1) {
      const problem = this.checkTerm(factors[i], [...loc, "mul", i], scope, depth + 1);
      if (problem) return problem;
    }
    // Degree, not "how many factors mention a variable": a product of two
    // variables is allowed in a rule and in a weighted objective, and
    // x * (y * z) must still be refused there, which counting factors cannot see.
    const order = degree(term);
    if (order <= 1) return null;
    if (!this.quadraticAllowed(loc)) {
      return refusal(
        "mul_not_linear",
        [...loc, "mul"],
        "both factors of this product contain a variable, which makes it quadratic; " +
          (loc[0] === "objective"
            ? "a lexicographic objective is solved one term at a time, holding each at its best, " +
              "and holding a quadratic term would need a quadratic rule"
            : "only a rule or a weighted objective may be quadratic")
      );
    }
    if (order > 2) {
      return refusal(
        "mul_not_quadratic",
        [...loc, "mul"],
        `this product multiplies ${order} variables together; ${
          loc[0] === "constraints" ? "a rule" : "an objective"
        } may be quadratic -- two variables at most -- and no higher`
      );
    }
    return null;
  }

  /** A rule and a weighted objective's terms may be quadratic; a
   * lexicographic objective stays linear (see `termMul`). */
  private quadraticAllowed(loc: IrLoc): boolean {
    if (loc[0] === "constraints") return true;
    if (loc[0] !== "objective") return false;
    const objective = this.ir.objective;
    const mode = isObject(objective) && typeof objective.mode === "string" ? objective.mode : "weighted";
    return mode === "weighted";
  }

  checkObjective(): IrRefusal | null {
    if (!("objective" in this.ir)) return null;
    const objective = this.ir.objective;
    if (!isObject(objective)) {
      return refusal(
        "objective_not_object",
        ["objective"],
        "objective is an object; omit the key entirely for a feasibility problem"
      );
    }
    const unknown = unknownKey(objective, OBJECTIVE_KEYS, ["objective"], "objective");
    if (unknown) return unknown;
    if (!(SENSES as readonly unknown[]).includes(objective.sense)) {
      return refusal(
        "objective_sense_unsupported",
        ["objective", "sense"],
        `${show(objective.sense)} is not a sense; an objective is ` +
          `${[...SENSES].sort().join(" or ")}`
      );
    }
    const mode = objective.mode ?? "weighted";
    if (!(OBJECTIVE_MODES as readonly unknown[]).includes(mode)) {
      return refusal(
        "objective_mode_unsupported",
        ["objective", "mode"],
        `${show(mode)} is not an objective mode; an objective is ` +
          `${[...OBJECTIVE_MODES].sort().join(" or ")}, or omit mode for a weighted sum`
      );
    }
    const terms = objective.terms;
    if (!Array.isArray(terms) || terms.length === 0) {
      return refusal(
        "objective_terms_invalid",
        ["objective", "terms"],
        "an objective carries a non-empty terms array; omit the objective otherwise"
      );
    }
    const seen = new Set<string>();
    for (let i = 0; i < terms.length; i += 1) {
      const term = terms[i];
      const at: IrLoc = ["objective", "terms", i];
      if (!isObject(term)) {
        return refusal("objective_term_malformed", at, "each objective term is an object");
      }
      const extra = unknownKey(term, OBJECTIVE_TERM_KEYS, at, "objective term");
      if (extra) return extra;
      if (!isName(term.id)) {
        return refusal(
          "objective_term_malformed",
          [...at, "id"],
          `${show(term.id)} is not a term id; ids are how a result says which part of the ` +
            "objective cost what"
        );
      }
      if (seen.has(term.id)) {
        return refusal(
          "objective_term_id_duplicated",
          [...at, "id"],
          `the objective term id '${term.id}' is used twice`
        );
      }
      seen.add(term.id);
      // A number, not only a whole one (benchmark re-test, October 2026).
      if (!isFiniteNumber(term.weight)) {
        return refusal(
          "objective_term_malformed",
          [...at, "weight"],
          `the term '${term.id}' must carry a number weight`
        );
      }
      if (!("expression" in term)) {
        return refusal(
          "objective_term_malformed",
          [...at, "expression"],
          `the term '${term.id}' has no expression, so it names a cost nothing defines`
        );
      }
      const problem = this.checkTerm(
        term.expression,
        [...at, "expression"],
        new Map<string, string>(),
        1
      );
      if (problem) return problem;
    }
    return null;
  }
}

/** Whether a term tree holds a `var` anywhere. Only ever called on a term
 * `checkTerm` has already accepted, so the shapes are known. */
/** How many variables multiply together in the worst part of a term: 0 for
 * data, 1 for linear, 2 for quadratic. Mirrors `_degree` in validate.py. */
function degree(term: unknown): number {
  if (!isObject(term)) return 0;
  if ("var" in term || "pwl" in term) return 1;
  // A function stands for a decision of its own when its argument reads one.
  if ("fn" in term) return degree(term.of) ? 1 : 0;
  // Likewise a prediction, when any input reads a decision (Epic ML).
  if ("predict" in term) return Array.isArray(term.of) && term.of.some((input: unknown) => degree(input) > 0) ? 1 : 0;
  if ("sum" in term) return degree(term.sum);
  if (Array.isArray(term.add)) return Math.max(0, ...term.add.map(degree));
  if (Array.isArray(term.mul)) return term.mul.reduce((total: number, child: unknown) => total + degree(child), 0);
  return 0;
}

/**
 * The first reason the contract refuses this document, or null. The
 * `domain` rules are not decided here; the server decides those.
 */
export function checkIrShape(ir: unknown): IrRefusal | null {
  // First, because every other rule walks the document.
  const serialised = JSON.stringify(ir) ?? "";
  // `TextEncoder` is what makes this the same number the server computes:
  // a multi-byte character is one `length` in JavaScript and several
  // bytes in Python's `len(...encode("utf-8"))`.
  const size = new TextEncoder().encode(serialised).length;
  if (size > MAX_IR_BYTES) {
    return refusal("ir_too_large", [], `this IR is ${size} bytes; the limit is ${MAX_IR_BYTES}`);
  }
  if (!isObject(ir)) return refusal("ir_not_object", [], "an IR is a JSON object");
  if (!("version" in ir)) {
    return refusal(
      "version_missing",
      ["version"],
      `an IR carries its version; this platform expresses version ${IR_VERSION}`
    );
  }
  if (typeof ir.version !== "number" || !ACCEPTED_VERSIONS.includes(ir.version)) {
    return refusal(
      "version_unsupported",
      ["version"],
      `${show(ir.version)} is not an IR version this platform expresses; it expresses ` +
        ACCEPTED_VERSIONS.join(" and ")
    );
  }
  for (const key of REQUIRED_KEYS) {
    if (!(key in ir)) {
      return refusal("key_missing", [key], `an IR states its ${key}, even when it has none`);
    }
  }
  const unknown = unknownKey(ir, ALL_KEYS, [], "model");
  if (unknown) return unknown;

  const checker = new ShapeChecker(ir);
  for (const step of [
    () => checker.checkSets(),
    () => checker.checkRelationships(),
    () => checker.checkParameters(),
    () => checker.checkPredictors(),
    () => checker.checkVariables(),
    () => checker.checkConstraints(),
    () => checker.checkObjective(),
  ]) {
    const problem = step();
    if (problem) return problem;
  }
  return null;
}

/** Convenience for a caller that only wants a yes or a no. */
export function isValidIrShape(ir: unknown): boolean {
  return checkIrShape(ir) === null;
}
