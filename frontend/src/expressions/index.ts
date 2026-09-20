/**
 * The shared expression core.
 *
 * One module owns the document format (`document.ts`), one owns what a
 * rule may name (`fields.ts`), one owns the comparisons (`operators.ts`),
 * one owns the function catalogue (`functions.ts`) -- and `validate.ts`
 * is the only thing that decides whether a document is usable. Task 14d's
 * server-side filter reads the same documents against the same catalogue;
 * `functions.ts` carries the SQL each entry compiles to, so the two cannot
 * drift apart silently.
 *
 * Consumers import from here.
 */
export {
  EXPRESSION_VERSION,
  countRules,
  emptyDocument,
  isEmptyDocument,
  isExpressionGroup,
  toDocument,
  toQuery,
} from "./document";
export type { ExpressionDocument, ExpressionGroup, ExpressionRule } from "./document";

export {
  COLUMN_GROUP,
  ENTITY_COLUMNS,
  RELATIONSHIP_DIRECTIONS,
  RELATIONSHIP_GROUP,
  buildFieldCatalogue,
  decodeFieldId,
  encodeFieldId,
  groupFields,
} from "./fields";
export type {
  EntityColumnName,
  ExpressionField,
  FieldCatalogue,
  FieldRef,
  RelationshipDirection,
} from "./fields";

export {
  EXPRESSION_OPERATORS,
  NULL_OPERATORS,
  OPERATORS_BY_TYPE,
  fieldAllowsOperator,
  operatorsForField,
} from "./operators";
export type { OperatorDef } from "./operators";

export { EXPRESSION_FUNCTIONS, FUNCTION_NAMES, functionReturnType } from "./functions";
export type { FunctionDef } from "./functions";

export {
  defaultFieldId,
  defaultOperatorFor,
  defaultRule,
  defaultValueFor,
  isUntouchedRule,
  withoutUntouchedRules,
} from "./defaults";

export { MAX_DEPTH, isValidExpression, validateExpression } from "./validate";
export type { ExpressionProblem, ExpressionWarning, ValidationResult } from "./validate";

export { degreeKey, evaluateExpression } from "./evaluate";
export type { EvaluationTarget } from "./evaluate";

export { graphCatalogue, graphTargets, matchingNodeIds } from "./graphFilter";

// `ExpressionBuilder` is deliberately NOT re-exported here. It is the only
// module that imports react-querybuilder at runtime, and re-exporting it
// from the barrel would pull the library (and its redux dependencies) into
// any bundle that wanted the validator. Import it lazily, as FilterBar
// does: `lazy(() => import("../expressions/ExpressionBuilder"))`.
