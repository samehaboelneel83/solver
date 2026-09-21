import type { EntityType } from "../api/v1";
import type { GraphResponse } from "../types/graph";
import {
  isExpressionGroup,
  type ExpressionDocument,
  type ExpressionGroup,
  type ExpressionRule,
} from "./document";
import {
  buildFieldCatalogue,
  RELATIONSHIP_DIRECTIONS,
  type ExpressionField,
  type FieldCatalogue,
  type RelationshipTypeRef,
} from "./fields";
import { degreeKey, evaluateExpression, type EvaluationTarget } from "./evaluate";

/**
 * The graph's adapter: what the loaded `GraphResponse` can honestly
 * answer.
 *
 * **The catalogue here offers no entity columns, deliberately.** The graph
 * wire contract carries `entity.attrs` verbatim and the relationships, but
 * not `key`, `sort_order` or `active` at all -- and its `label` is
 * `entity.label OR entity.key` (`graph/service.py:_node_label`), which is
 * not the `label` column. Offering them would mean the same document
 * filtered one way on this canvas and another way in Task 14d's SQL, which
 * is worse than a rule that cannot be written. (The brief lists the four
 * columns under the shared catalogue; they are there, and `buildFieldCatalogue`
 * serves them to a consumer that has them.)
 *
 * Filtering is client-side over the graph already in memory: no endpoint,
 * no round trip.
 *
 * A rule about one type does not hide the others. `evaluateExpression`
 * is fail-closed on a type mismatch -- that is the SQL a list filter
 * compiles, and an employee-only page wants it. This canvas is a picture
 * of the whole domain, so a condition that is not about a node is not a
 * reason to take it off. Relationship counts still apply to every type.
 */

export function graphCatalogue(
  entityTypes: readonly EntityType[],
  relationshipTypes: readonly RelationshipTypeRef[]
): FieldCatalogue {
  return buildFieldCatalogue({ entityTypes, relationshipTypes, columns: [] });
}

/**
 * One evaluation target per node, with its relationship counts.
 *
 * A node whose entity type is not in the payload is left out rather than
 * given a guessed type: it cannot satisfy a rule about any type's
 * attribute, and inventing one would make it satisfy the wrong one.
 */
export function graphTargets(graph: GraphResponse): Map<string, EvaluationTarget> {
  const entityTypeIdByName = new Map(graph.entity_types.map((t) => [t.name, t.id]));
  const relationshipTypeIdByName = new Map(graph.relationship_types.map((t) => [t.name, t.id]));

  const degrees = new Map<string, Map<string, number>>();
  const bump = (nodeId: string, relationshipTypeId: string, direction: (typeof RELATIONSHIP_DIRECTIONS)[number]) => {
    let byKey = degrees.get(nodeId);
    if (!byKey) {
      byKey = new Map();
      degrees.set(nodeId, byKey);
    }
    const key = degreeKey(relationshipTypeId, direction);
    byKey.set(key, (byKey.get(key) ?? 0) + 1);
  };

  for (const edge of graph.edges) {
    const relationshipTypeId = relationshipTypeIdByName.get(edge.type);
    if (relationshipTypeId === undefined) continue;
    bump(edge.source, relationshipTypeId, "outgoing");
    bump(edge.target, relationshipTypeId, "incoming");
    bump(edge.source, relationshipTypeId, "any");
    // A self-loop is ONE relationship row; counting it at both ends would
    // report two where the database holds one.
    if (edge.target !== edge.source) bump(edge.target, relationshipTypeId, "any");
  }

  const targets = new Map<string, EvaluationTarget>();
  for (const node of graph.nodes) {
    const entityTypeId = entityTypeIdByName.get(node.type);
    if (entityTypeId === undefined) continue;
    targets.set(node.id, {
      entityTypeId,
      columns: {},
      attrs: node.attributes ?? {},
      degrees: degrees.get(node.id) ?? new Map(),
    });
  }
  return targets;
}

/** The entity type an attribute field belongs to, or null for a field
 * every node has (a column, a relationship count). */
function ownerEntityTypeId(field: ExpressionField): string | null {
  const ref = field.ref.kind === "function" ? field.ref.argument : field.ref;
  return ref.kind === "attribute" ? ref.entityTypeId : null;
}

/**
 * Drop rules that name a different entity type. An empty group after
 * pruning is "this constraint does not apply", including a negated one:
 * `NOT (unit.capacity > 5)` hiding every shift would be the same bug
 * with a minus sign.
 */
function pruneGroup(
  group: ExpressionGroup,
  catalogue: FieldCatalogue,
  entityTypeId: string
): ExpressionGroup | null {
  const rules: (ExpressionRule | ExpressionGroup)[] = [];
  for (const node of group.rules) {
    if (isExpressionGroup(node)) {
      const inner = pruneGroup(node, catalogue, entityTypeId);
      if (inner) rules.push(inner);
      continue;
    }
    const field = catalogue.get(node.field);
    // An unresolvable field stays: evaluateExpression is false for it,
    // which is the same failure as a typed-out rule on an entity list.
    const owner = field ? ownerEntityTypeId(field) : null;
    if (!field || owner === null || owner === entityTypeId) rules.push(node);
  }
  if (rules.length === 0) return null;
  const next: ExpressionGroup = { combinator: group.combinator, rules };
  if (group.not) next.not = true;
  return next;
}

/** The ids of the nodes the expression matches. */
export function matchingNodeIds(
  graph: GraphResponse,
  catalogue: FieldCatalogue,
  document: ExpressionDocument
): Set<string> {
  const targets = graphTargets(graph);
  const matched = new Set<string>();
  for (const node of graph.nodes) {
    const target = targets.get(node.id);
    if (!target) {
      // An untypable node cannot satisfy a rule -- except that an empty
      // expression constrains nothing, and it should not vanish then.
      if (document.query.rules.length === 0) matched.add(node.id);
      continue;
    }
    const query = pruneGroup(document.query, catalogue, target.entityTypeId);
    if (!query || evaluateExpression({ version: document.version, query }, catalogue, target)) {
      matched.add(node.id);
    }
  }
  return matched;
}
