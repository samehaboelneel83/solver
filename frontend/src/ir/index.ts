/**
 * The problem IR contract, client side.
 *
 * `contract.ts` restates the vocabulary that `backend/app/ir/contract.json`
 * defines (pinned by `parity.test.ts`); `validate.ts` decides every rule
 * the contract marks `shape`, which is every rule that needs no database.
 * The rules marked `domain` belong to the server alone.
 *
 * Consumers import from here.
 */
export {
  ALL_KEYS,
  ARITHMETIC_ATTR_TYPES,
  CONSTRAINT_KEYS,
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
  SEVERITIES,
  SHAPE_RULES,
  TERM_KINDS,
  VARIABLE_DOMAINS,
  isName,
} from "./contract";
export type { IrRule, Relation, RuleWhere, Sense, Severity, TermKind, VariableDomain } from "./contract";

export { checkIrShape, isValidIrShape } from "./validate";
export type { IrLoc, IrRefusal } from "./validate";
