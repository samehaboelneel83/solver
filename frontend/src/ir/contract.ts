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

export const VARIABLE_DOMAINS = ["binary", "integer", "continuous", "interval"] as const;
/** How a parameter's values may be uncertain (version 2). */
export const UNCERTAINTY_KINDS = ["interval", "scenarios"] as const;
export const RELATIONS = ["<=", "=", ">="] as const;
/** How far a `via` binding walks. `one` is a single edge; `any` is the
 * transitive closure; `any_or_self` is that plus the anchor itself, which
 * is the shape `entity_descendants()` has always returned ("node +
 * everything beneath it") and the one a planner means by "counting its
 * sub-units". */
export const TRAVERSAL_DEPTHS = ["one", "any", "any_or_self"] as const;
/** How an edge attribute read along a repeated walk (queue R19) combines the
 * path's edges: `sum` (a distance up a chain), `min` / `max` (the tightest
 * capacity), `product` (a yield), `count` (the edges carrying it). */
export const PATH_COMBINATIONS = ["count", "max", "min", "product", "sum"] as const;
/** A scope entry for an edge a `via` names with `as`: `EDGE_MARK + rel + "/" + depth`. */
export const EDGE_MARK = "@";
export const SEVERITIES = ["hard", "soft"] as const;
export const SENSES = ["minimize", "maximize"] as const;
export const OBJECTIVE_MODES = ["weighted", "lex"] as const;
export const TERM_KINDS = ["const", "par", "var", "attr", "sum", "add", "mul", "pwl", "fn"] as const;
export const FILTER_OPERATORS = ["=", "!=", "<", "<=", ">", ">=", "in", "notIn"] as const;
export const ARITHMETIC_ATTR_TYPES = ["integer", "number"] as const;

export const FUNCTION_CONVEXITIES = ["convex", "concave", "neither"] as const;
export const FUNCTION_MONOTONICITY = ["increasing", "decreasing", "none"] as const;
export const FUNCTION_DOMAINS = ["any", "nonnegative", "positive"] as const;

export type FunctionSpec = {
  text: string;
  convexity: (typeof FUNCTION_CONVEXITIES)[number];
  monotone: (typeof FUNCTION_MONOTONICITY)[number];
  domain: (typeof FUNCTION_DOMAINS)[number];
};

/** The closed catalogue a `fn` term names (version 2): each a function of
 * one argument, labelled with its curvature over its whole domain, whether
 * it only rises, and where it is defined. */
export const FUNCTIONS: Readonly<Record<string, FunctionSpec>> = {
  exp: { text: "e raised to the argument", convexity: "convex", monotone: "increasing", domain: "any" },
  log: { text: "the natural logarithm", convexity: "concave", monotone: "increasing", domain: "positive" },
  sqrt: { text: "the square root", convexity: "concave", monotone: "increasing", domain: "nonnegative" },
  abs: { text: "the absolute value", convexity: "convex", monotone: "none", domain: "any" },
  sin: { text: "the sine, in radians", convexity: "neither", monotone: "none", domain: "any" },
  cos: { text: "the cosine, in radians", convexity: "neither", monotone: "none", domain: "any" },
};

export type VariableDomain = (typeof VARIABLE_DOMAINS)[number];
export type Relation = (typeof RELATIONS)[number];
export type Severity = (typeof SEVERITIES)[number];
export type Sense = (typeof SENSES)[number];
export type ObjectiveMode = (typeof OBJECTIVE_MODES)[number];
export type TermKind = (typeof TERM_KINDS)[number];
export type TraversalDepth = (typeof TRAVERSAL_DEPTHS)[number];
export type PathCombination = (typeof PATH_COMBINATIONS)[number];

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
    text: "a constraint that is not a scheduling rule states `left`, `relation` and `right`; a declared but unexpressed constraint is not a model",
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
  {
    code: "when_needs_version_2",
    where: "shape",
    text: "a constraint's `when` appears only in a version 2 document",
  },
  {
    code: "when_malformed",
    where: "shape",
    text: "a `when` is an object naming a `var`, its `index`, and optionally `is` (0 or 1)",
  },
  {
    code: "when_not_binary",
    where: "shape",
    text: "the variable a `when` names is declared binary",
  },
  { code: "when_on_soft", where: "shape", text: "a `when` is on a hard constraint" },
  { code: "when_on_product", where: "shape", text: "a constraint with a `when` is linear" },
  {
    code: "pwl_needs_version_2",
    where: "shape",
    text: "a `pwl` term appears only in a version 2 document",
  },
  {
    code: "pwl_malformed",
    where: "shape",
    text: "a `pwl` names one variable and at least two `[x, y]` points of numbers",
  },
  {
    code: "pwl_breakpoints_not_increasing",
    where: "shape",
    text: "a `pwl`'s points are in strictly increasing `x`",
  },
  {
    code: "fn_needs_version_2",
    where: "shape",
    text: "a `fn` term appears only in a version 2 document",
  },
  {
    code: "fn_unknown",
    where: "shape",
    text: "a `fn` names a function in the contract's `functions` catalogue",
  },
  { code: "fn_malformed", where: "shape", text: "a `fn` carries its argument, a term, in `of`" },
  {
    code: "fn_argument_nonlinear",
    where: "shape",
    text: "a function's argument is linear: no part of it multiplies two decisions",
  },
  {
    code: "interval_needs_version_2",
    where: "shape",
    text: "the `interval` domain appears only in a version 2 document",
  },
  {
    code: "interval_malformed",
    where: "shape",
    text: "an interval names its `start`, `end` and `size` (and optionally `presence`) and carries no bounds; no other variable carries those keys",
  },
  {
    code: "interval_part_invalid",
    where: "shape",
    text: "an interval's `start` and `end` are integer variables, and its `presence` a binary one, each declared with the interval's own index",
  },
  {
    code: "interval_size_invalid",
    where: "shape",
    text: "an interval's `size` is a non-negative whole number or a parameter declared with the interval's own index",
  },
  {
    code: "interval_read_as_number",
    where: "shape",
    text: "a `var` term never names an interval; its `start` and `end` variables are the numbers",
  },
  {
    code: "scheduling_needs_version_2",
    where: "shape",
    text: "a `no_overlap` or `cumulative` rule appears only in a version 2 document",
  },
  {
    code: "scheduling_rule_malformed",
    where: "shape",
    text: "a constraint is either an expression (`left`, `relation`, `right`) or exactly one scheduling rule; `no_overlap` carries an `interval` and an `over`, `cumulative` also a `demand` and a `capacity`",
  },
  {
    code: "scheduling_not_interval",
    where: "shape",
    text: "a scheduling rule's `interval` names an interval variable",
  },
  {
    code: "scheduling_rule_hard",
    where: "shape",
    text: "a scheduling rule is hard: no weight, no `when`",
  },
  {
    code: "scheduling_amount_not_constant",
    where: "shape",
    text: "a `cumulative`'s `demand` and `capacity` read no variable",
  },
  {
    code: "uncertainty_needs_version_2",
    where: "shape",
    text: "a parameter's `uncertainty` appears only in a version 2 document",
  },
  {
    code: "uncertainty_malformed",
    where: "shape",
    text: "an `uncertainty` is `{kind: interval, deviation, gamma?}` -- deviation a non-negative fraction of each value, gamma a non-negative number of cells that may deviate at once -- or `{kind: scenarios}`",
  },
  {
    code: "stage_needs_version_2",
    where: "shape",
    text: "a variable's `stage` appears only in a version 2 document",
  },
  {
    code: "stage_invalid",
    where: "shape",
    text: "a variable's `stage` is 1 (decided now) or 2 (decided once the uncertain data is known), and an interval has none",
  },
  {
    code: "chance_needs_version_2",
    where: "shape",
    text: "a constraint's `chance` appears only in a version 2 document",
  },
  {
    code: "chance_malformed",
    where: "shape",
    text: "a `chance` is `{epsilon}`, the share of futures the rule may fail in, strictly between 0 and 1",
  },
  {
    code: "chance_misplaced",
    where: "shape",
    text: "a `chance` is on a hard, linear expression rule with no `when` -- not a soft, conditional, scheduling, connected or route one",
  },
  {
    code: "connected_needs_version_2",
    where: "shape",
    text: "a `connected` rule appears only in a version 2 document",
  },
  {
    code: "connected_malformed",
    where: "shape",
    text: "a `connected` names `assign`, `units`, `groups` and `via`, and optionally `empty` (`forbidden` or `allowed`), and is not also an expression or inside a `forall`",
  },
  {
    code: "connected_not_binary",
    where: "shape",
    text: "a `connected` rule's variable is declared binary",
  },
  {
    code: "connected_index_mismatch",
    where: "shape",
    text: "a `connected` rule's variable is indexed by its units' index, then its groups' index",
  },
  {
    code: "connected_via_invalid",
    where: "shape",
    text: "a `connected` rule's `via` is a declared relationship",
  },
  {
    code: "connected_on_soft",
    where: "shape",
    text: "a `connected` rule is hard and unconditional",
  },
  {
    code: "connected_via_not_self",
    where: "domain",
    text: "a `connected` rule's `via` joins the units' entity type to itself",
  },  {
    code: "route_needs_version_2",
    where: "shape",
    text: "a `route` rule appears only in a version 2 document",
  },
  {
    code: "route_malformed",
    where: "shape",
    text: "a `route` names `visit`, `vehicles`, `stops` and `depot`, and optionally `demand` and `capacity` (both or neither), and is not also an expression or inside a `forall`",
  },
  {
    code: "route_not_binary",
    where: "shape",
    text: "a `route` rule's variable is declared binary",
  },
  {
    code: "route_index_mismatch",
    where: "shape",
    text: "a `route` rule's variable is indexed by its vehicles' index, its stops' index, then a third index over the stops",
  },
  {
    code: "route_on_soft",
    where: "shape",
    text: "a `route` rule is hard and unconditional",
  },
  {
    code: "edge_needs_version_2",
    where: "shape",
    text: "a `via` names the edge it walks with `as` in a version 2 document only",
  },
  {
    code: "binding_via_as_invalid",
    where: "shape",
    text: "a `via`'s `as` is a name not already bound, and not the binding's own index",
  },
  {
    code: "edge_not_an_index",
    where: "shape",
    text: "an edge named by `as` is read with `attr` only, never used as an index or an anchor",
  },
  {
    code: "attr_along_invalid",
    where: "shape",
    text: "an `attr` of an edge walked more than once says how the path combines it in `along`; any other `attr` has no `along`",
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
  "when",
  // A chance rule (version 2): may fail in at most a share of the futures.
  "chance",
  // Scheduling rules (version 2), in place of left/relation/right.
  "no_overlap",
  "cumulative",
  // The connectivity rule (version 2), likewise.
  "connected",
  // The routing rule (version 2, queue R15b), likewise.
  "route",
]);

/** The two scheduling rules, and the keys each carries (`SCHEDULING_KEYS`
 * in `app/ir/contract.py`). */
export const SCHEDULING_KEYS: Readonly<Record<"no_overlap" | "cumulative", readonly string[]>> = {
  no_overlap: ["interval", "over"],
  cumulative: ["interval", "over", "demand", "capacity"],
};

/** What a `connected` rule names; `empty` is optional (`CONNECTED_KEYS`). */
export const CONNECTED_KEYS: readonly string[] = ["assign", "units", "groups", "via", "empty"];

/** What a `route` rule names; `demand` and `capacity` are optional, both or neither (`ROUTE_KEYS`). */
export const ROUTE_KEYS: readonly string[] = ["visit", "vehicles", "stops", "depot", "demand", "capacity"];

/** What an interval declaration names beyond `index` and `domain`. */
export const INTERVAL_KEYS = ["start", "end", "size", "presence"] as const;
