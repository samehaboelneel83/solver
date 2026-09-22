/**
 * The problem IR contract, as the browser holds it.
 *
 * The one artefact is `backend/app/ir/contract.json`; this is the
 * TypeScript restatement of it, for the same reason `operators.ts` and
 * `functions.ts` restate the expression catalogue (Task 14c): the builder
 * needs the types and the bundler needs to tree-shake, and nothing under
 * `src/` may import across the repository boundary or Vite would try to
 * bundle a backend file.
 *
 * `parity.test.ts` reads the JSON off disk and deep-compares it with what
 * is here, so the two cannot drift. That test is the mechanism; this file
 * is not the definition.
 *
 * The prose the numbers mean is in `docs/contracts/problem-ir.md`.
 */

/** The version this platform writes. */
export const IR_VERSION = 2;
/** The versions it reads: version 2 is version 1 plus what Phase 10 adds. */
export const ACCEPTED_VERSIONS: readonly number[] = [1, 2];

export const MAX_DEPTH = 12;
export const MAX_TERMS = 500;
export const MAX_INDICES = 6;
export const MAX_IR_BYTES = 262144;

/** `entity_type.name`, `attribute_def.name` and `parameter_def.name` all
 * carry this CHECK "because the names are used verbatim in IR
 * expressions" (migration 0006). This is the IR end of that sentence. */
export const NAME_PATTERN = "^[a-z][a-z0-9_]*$";

/** Anchored with `^...$` and used with `.test`, which in JavaScript --
 * unlike Python's `re.match` -- does not also match before a trailing
 * newline, so `"employee\n"` is refused here exactly as Postgres refuses
 * it. */
const NAME_RE = new RegExp(NAME_PATTERN);

export function isName(value: unknown): value is string {
  return typeof value === "string" && NAME_RE.test(value);
}

export const REQUIRED_KEYS = ["version", "sets", "parameters", "variables", "constraints"] as const;
export const OPTIONAL_KEYS = ["objective", "relationships"] as const;
export const ALL_KEYS: ReadonlySet<string> = new Set<string>([...REQUIRED_KEYS, ...OPTIONAL_KEYS]);

export const VARIABLE_DOMAINS = ["binary", "integer", "continuous"] as const;
export const RELATIONS = ["<=", "=", ">="] as const;
/** How far a `via` binding walks. `one` is a single edge; `any` is the
 * transitive closure; `any_or_self` is that plus the anchor itself, which
 * is the shape `entity_descendants()` has always returned ("node +
 * everything beneath it") and the one a planner means by "counting its
 * sub-units". */
export const TRAVERSAL_DEPTHS = ["one", "any", "any_or_self"] as const;
export const SEVERITIES = ["hard", "soft"] as const;
export const SENSES = ["minimize", "maximize"] as const;
export const OBJECTIVE_MODES = ["weighted", "lex"] as const;
export const TERM_KINDS = ["const", "par", "var", "attr", "sum", "add", "mul"] as const;
export const FILTER_OPERATORS = ["=", "!=", "<", "<=", ">", ">=", "in", "notIn"] as const;
export const ARITHMETIC_ATTR_TYPES = ["integer", "number"] as const;

export type VariableDomain = (typeof VARIABLE_DOMAINS)[number];
export type Relation = (typeof RELATIONS)[number];
export type Severity = (typeof SEVERITIES)[number];
export type Sense = (typeof SENSES)[number];
export type ObjectiveMode = (typeof OBJECTIVE_MODES)[number];
export type TermKind = (typeof TERM_KINDS)[number];
export type TraversalDepth = (typeof TRAVERSAL_DEPTHS)[number];

/** Where a rule can be decided. `shape` rules are the ones this half of
 * the platform can judge; `domain` rules need the domain's own rows and
 * belong to the server alone. */
export type RuleWhere = "shape" | "domain";

export type IrRule = { code: string; where: RuleWhere; text: string };

/** Every reason an IR can be refused, in the order the JSON declares
 * them. `backend/tests/ir_fixtures.json` carries at least one invalid
 * document per code. */
export const IR_RULES: readonly IrRule[] = [
  { code: "ir_not_object", where: "shape", text: "the IR is a JSON object" },
  { code: "version_missing", where: "shape", text: "`version` is present" },
  {
    code: "version_unsupported",
    where: "shape",
    text: "`version` is a version this platform expresses",
  },
  { code: "key_missing", where: "shape", text: "every required top-level key is present" },
  {
    code: "key_unknown",
    where: "shape",
    text: "no key beyond the contract's -- at the top level, on a declaration, on a constraint, on a binding, on a filter or on a term",
  },
  { code: "sets_not_array", where: "shape", text: "`sets` is an array" },
  {
    code: "set_not_a_name",
    where: "shape",
    text: "each set is an entity type name matching the name pattern",
  },
  { code: "set_duplicated", where: "shape", text: "a set is named once" },
  { code: "relationships_not_array", where: "shape", text: "`relationships` is an array" },
  {
    code: "relationship_not_a_name",
    where: "shape",
    text: "each relationship is a relationship type name matching the name pattern",
  },
  { code: "relationship_duplicated", where: "shape", text: "a relationship is named once" },
  {
    code: "parameters_not_object",
    where: "shape",
    text: "`parameters` is an object keyed by parameter name",
  },
  {
    code: "parameter_not_a_name",
    where: "shape",
    text: "each parameter key matches the name pattern",
  },
  {
    code: "parameter_not_object",
    where: "shape",
    text: "each parameter declaration is an object",
  },
  {
    code: "parameter_index_not_array",
    where: "shape",
    text: "a parameter declares `index` as an array of set names",
  },
  {
    code: "parameter_index_not_declared",
    where: "shape",
    text: "every set a parameter is indexed by is declared in `sets`",
  },
  {
    code: "variables_not_object",
    where: "shape",
    text: "`variables` is an object keyed by variable name",
  },
  { code: "variables_empty", where: "shape", text: "a model declares at least one variable" },
  {
    code: "variable_not_a_name",
    where: "shape",
    text: "each variable key matches the name pattern",
  },
  { code: "variable_not_object", where: "shape", text: "each variable declaration is an object" },
  {
    code: "variable_index_not_array",
    where: "shape",
    text: "a variable declares `index` as an array of set names",
  },
  {
    code: "variable_index_not_declared",
    where: "shape",
    text: "every set a variable is indexed by is declared in `sets`",
  },
  { code: "variable_domain_missing", where: "shape", text: "a variable declares a `domain`" },
  {
    code: "variable_domain_unsupported",
    where: "shape",
    text: "a variable's `domain` is one this version solves",
  },
  {
    code: "variable_bounds_invalid",
    where: "shape",
    text:
      "`lower` and `upper` are numbers with lower <= upper, and belong only to an integer or continuous variable",
  },
  { code: "constraints_not_array", where: "shape", text: "`constraints` is an array" },
  { code: "constraint_not_object", where: "shape", text: "each constraint is an object" },
  {
    code: "constraint_id_not_a_name",
    where: "shape",
    text: "a constraint's `id` matches the name pattern",
  },
  { code: "constraint_id_duplicated", where: "shape", text: "a constraint id is used once" },
  {
    code: "constraint_expression_missing",
    where: "shape",
    text: "a constraint states `left`, `relation` and `right`; a declared but unexpressed constraint is not a model",
  },
  {
    code: "constraint_relation_unsupported",
    where: "shape",
    text: "a constraint's `relation` is one this version expresses",
  },
  {
    code: "constraint_severity_unsupported",
    where: "shape",
    text: "a constraint's `severity` is `hard` or `soft`",
  },
  {
    code: "constraint_weight_invalid",
    where: "shape",
    text: "a soft constraint carries a positive integer `weight`; a hard one carries none",
  },
  { code: "binding_not_object", where: "shape", text: "each index binding is an object" },
  {
    code: "binding_index_not_a_name",
    where: "shape",
    text: "a binding's `index` matches the name pattern",
  },
  {
    code: "binding_index_duplicated",
    where: "shape",
    text: "an index name is bound once in a scope",
  },
  {
    code: "binding_set_not_declared",
    where: "shape",
    text: "a binding's `set` is declared in `sets`",
  },
  {
    code: "bindings_invalid",
    where: "shape",
    text: "`forall` and a sum's `over` are arrays binding between one index and the limit",
  },
  { code: "binding_via_not_object", where: "shape", text: "a binding's `via` is an object" },
  {
    code: "binding_via_rel_not_declared",
    where: "shape",
    text: "a `via`'s `rel` is declared in `relationships`",
  },
  {
    code: "binding_via_anchor_invalid",
    where: "shape",
    text: "a `via` names exactly one of `from` or `to`, and it is an index name",
  },
  {
    code: "binding_via_anchor_not_bound",
    where: "shape",
    text: "a `via`'s anchor index is already bound where the traversal starts",
  },
  {
    code: "binding_via_depth_unsupported",
    where: "shape",
    text: "a `via`'s `depth` is one this version walks",
  },
  { code: "where_not_array", where: "shape", text: "a binding's `where` is an array of filters" },
  {
    code: "where_filter_malformed",
    where: "shape",
    text: "each filter names an `attr`, an `op` and a `value`",
  },
  {
    code: "where_operator_unknown",
    where: "shape",
    text: "a filter's `op` is one of the contract's filter operators",
  },
  {
    code: "term_not_object",
    where: "shape",
    text: "a term, and every object-valued part of one, is in the shape the contract gives it",
  },
  { code: "term_kind_unknown", where: "shape", text: "a term names one of the contract's kinds" },
  { code: "term_kind_ambiguous", where: "shape", text: "a term names exactly one kind" },
  { code: "const_not_a_number", where: "shape", text: "a `const` is a finite number" },
  {
    code: "reference_undeclared",
    where: "shape",
    text: "a `par` or `var` term names something the IR declares",
  },
  {
    code: "reference_index_arity",
    where: "shape",
    text: "a `par` or `var` is subscripted with as many indices as it is declared with",
  },
  {
    code: "index_not_bound",
    where: "shape",
    text: "every index a term uses is bound by an enclosing `forall` or `over`",
  },
  {
    code: "index_set_mismatch",
    where: "shape",
    text: "an index used at a position is bound to the set declared at that position",
  },
  { code: "sum_malformed", where: "shape", text: "a `sum` carries a body term and an `over`" },
  { code: "add_empty", where: "shape", text: "an `add` has at least one summand" },
  { code: "mul_arity", where: "shape", text: "a `mul` has exactly two factors" },
  {
    code: "mul_not_linear",
    where: "shape",
    text: "a `mul` in a lexicographic objective has at most one factor that contains a variable",
  },
  {
    code: "mul_not_quadratic",
    where: "shape",
    text: "a rule or a weighted objective term is at most quadratic: no product of more than two variables",
  },
  { code: "depth_exceeded", where: "shape", text: "a term nests no deeper than the limit" },
  { code: "terms_exceeded", where: "shape", text: "an IR holds no more terms than the limit" },
  {
    code: "ir_too_large",
    where: "shape",
    text: "an IR serialises to no more than the byte limit",
  },
  { code: "objective_not_object", where: "shape", text: "`objective`, when present, is an object" },
  {
    code: "objective_sense_unsupported",
    where: "shape",
    text: "an objective's `sense` is `minimize` or `maximize`",
  },
  {
    code: "objective_mode_unsupported",
    where: "shape",
    text: "an objective's `mode` is `weighted` or `lex`; omit it for a weighted sum",
  },
  {
    code: "objective_terms_invalid",
    where: "shape",
    text: "an objective carries a non-empty `terms` array",
  },
  {
    code: "objective_term_malformed",
    where: "shape",
    text: "each objective term carries an `id`, an integer `weight` and an `expression`",
  },
  {
    code: "objective_term_id_duplicated",
    where: "shape",
    text: "an objective term id is used once",
  },

  {
    code: "set_not_in_domain",
    where: "domain",
    text: "every declared set is an entity type of the problem's domain",
  },
  {
    code: "relationship_not_in_domain",
    where: "domain",
    text: "every declared relationship is a relationship type of the problem's domain",
  },
  {
    code: "binding_via_endpoint_mismatch",
    where: "domain",
    text:
      "a `via`'s anchor and bound sets are the relationship type's own endpoint types, " +
      "the right way round",
  },
  {
    code: "binding_via_depth_not_transitive",
    where: "domain",
    text: "a repeated `via` walks a relationship whose two ends are the same entity type",
  },
  {
    code: "parameter_not_in_domain",
    where: "domain",
    text: "every declared parameter is a parameter of the problem's domain",
  },
  {
    code: "parameter_index_mismatch",
    where: "domain",
    text: "a parameter's declared index is the domain's own index types, in order",
  },
  {
    code: "attribute_not_declared",
    where: "domain",
    text: "an `attr` names an attribute the bound set declares",
  },
  {
    code: "attribute_not_arithmetic",
    where: "domain",
    text: "an `attr` used as a number has an arithmetic data type",
  },
  {
    code: "where_operator_not_offered",
    where: "domain",
    text: "a filter's operator is one the attribute's data type offers",
  },
  {
    code: "where_value_not_of_type",
    where: "domain",
    text: "a filter's value is a value of the attribute's data type",
  },
];

export const SHAPE_RULES: ReadonlySet<string> = new Set(
  IR_RULES.filter((rule) => rule.where === "shape").map((rule) => rule.code)
);
export const DOMAIN_RULES: ReadonlySet<string> = new Set(
  IR_RULES.filter((rule) => rule.where === "domain").map((rule) => rule.code)
);

/** The keys a constraint may carry. Not in the shared JSON: they are the
 * contract's prose, and `key_unknown` is what a typo lands on. Kept in
 * step with `CONSTRAINT_KEYS` in `app/ir/contract.py` by the fixture for
 * that rule, which names one. */
export const CONSTRAINT_KEYS: ReadonlySet<string> = new Set([
  "id",
  "note",
  "forall",
  "left",
  "relation",
  "right",
  "severity",
  "weight",
]);
