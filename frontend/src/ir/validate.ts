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
  CONSTRAINT_KEYS,
  FILTER_OPERATORS,
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
const VIA_KEYS: ReadonlySet<string> = new Set(["rel", "from", "to", "depth"]);
const FILTER_KEYS: ReadonlySet<string> = new Set(["attr", "op", "value"]);
const VARIABLE_KEYS: ReadonlySet<string> = new Set(["index", "domain", "lower", "upper"]);
const PARAMETER_KEYS: ReadonlySet<string> = new Set(["index"]);
const OBJECTIVE_KEYS: ReadonlySet<string> = new Set(["sense", "terms", "mode"]);
const OBJECTIVE_TERM_KEYS: ReadonlySet<string> = new Set(["id", "weight", "expression"]);
const TERM_KEYS: Record<string, readonly string[]> = {
  const: [],
  par: ["index"],
  var: ["index"],
  attr: [],
  sum: ["over"],
  add: [],
  mul: [],
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
  readonly variables = new Map<string, string[]>();
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
        index.length < 1 ||
        index.length > MAX_INDICES ||
        !index.every((s) => typeof s === "string")
      ) {
        return refusal(
          "parameter_index_not_array",
          [...at, "index"],
          `'${name}' must declare index as an array of 1 to ${MAX_INDICES} set names, in the ` +
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
      this.parameters.set(name, index as string[]);
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
      const bounds = this.checkBounds(name, declaration, at);
      if (bounds) return bounds;
      this.variables.set(name, index as string[]);
    }
    return null;
  }

  private checkBounds(name: string, declaration: Json, at: IrLoc): IrRefusal | null {
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
      const where = this.checkWhere(binding, at);
      if (where) return where;
    }
    return scope;
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

    const ends = (["from", "to"] as const).filter((end) => end in via);
    if (ends.length !== 1 || !isName(via[ends[0]])) {
      return refusal(
        "binding_via_anchor_invalid",
        here,
        "a via names exactly one of from or to, and it is the index the walk starts at; the " +
          "end named is where that index sits, so this binding takes the other"
      );
    }
    const anchor = via[ends[0]] as string;
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
    return null;
  }

  private checkWhere(binding: Json, at: IrLoc): IrRefusal | null {
    if (!("where" in binding)) return null;
    const filters = binding.where;
    if (!Array.isArray(filters)) {
      return refusal(
        "where_not_array",
        [...at, "where"],
        `where is an array of filters, combined with and; version ${IR_VERSION} has no groups ` +
          "and no or"
      );
    }
    for (let k = 0; k < filters.length; k += 1) {
      const entry = filters[k];
      const here: IrLoc = [...at, "where", k];
      if (!isObject(entry)) {
        return refusal("where_filter_malformed", here, "each filter must be an object");
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
        return this.reference(term, loc, scope, "par", this.parameters);
      case "var":
        return this.reference(term, loc, scope, "var", this.variables);
      case "attr":
        return this.termAttr(term, loc, scope);
      case "sum":
        return this.termSum(term, loc, scope, depth);
      case "add":
        return this.termAdd(term, loc, scope, depth);
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
      Object.keys(reference).length !== 2 ||
      !("of" in reference) ||
      !("name" in reference)
    ) {
      return refusal(
        "term_not_object",
        [...loc, "attr"],
        'an attr term is {"of": <index>, "name": <attribute>}'
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
      if (!isInt(term.weight)) {
        return refusal(
          "objective_term_malformed",
          [...at, "weight"],
          `the term '${term.id}' must carry an integer weight`
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
  if ("var" in term) return 1;
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
